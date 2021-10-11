import fnmatch
import logging
import os
import sqlite3
import tarfile
import typing as t
from abc import ABC, abstractmethod
from collections import UserDict
from functools import lru_cache
from io import BufferedIOBase, FileIO, IOBase
from pathlib import Path
from shutil import copyfile
from zipfile import ZipFile

from .db import open_sqlite_db_readonly
from .utils import is_platform_windows

# Types
FileList = list[t.AnyStr]
SubFolders = list[t.AnyStr]

logger_log = logging.getLogger("xleapp.logfile")
logger_process = logging.getLogger("xleapp.process")


class PathValidator:
    def __set_name__(self, owner, name):
        self.name = str(name)

    def __get__(self, obj, type=None):
        return obj.__dict__.get(self.name) or None

    def __set__(self, obj, value):
        obj.__dict__[self.name] = value.resolve()


class HandleValidator:
    def __set_name__(self, owner, name):
        self.name = str(name)
        self.path = "path"

    def __get__(self, obj, type=None):
        return obj.__dict__.get(self.name) or None

    def __set__(self, obj, value):
        path: Path = getattr(obj, self.path, None)
        if isinstance(value, str) or isinstance(value, Path):
            value = None

        setattr(obj, self.path, path)
        obj.__dict__[self.name] = value


class Handle:
    h: t.Union[sqlite3.Connection, FileIO, str] = HandleValidator()
    path: Path = PathValidator()

    def __init__(self, file: t.Any, path: t.Any = None) -> None:
        self.path = path
        self.h = file

    def __call__(self):
        return self.h or self.path


class FileHandles(UserDict):
    logged: list = []

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(self, *args, **kwargs)
        self.default_factory = set

    def __len__(self):
        return sum(count for count in self.values())

    def add(self, regex: str, files: list, file_names_only: bool = False) -> None:

        if self.get(regex):
            return

        for item in files:

            """
            If we have more then 10 files, then set only
            file names instead of `FileIO` or
            `sqlite3.connection` to save memory. Most artifacts
            probably have less then 5 files they will read/use.
            """
            h = None
            if len(files) > 10 or file_names_only:
                h = Handle(item)
            else:
                if item.drive.startswith("\\\\?\\"):
                    extended_path = Path(item)

                path = Path(item.resolve())

                try:
                    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                    cursor = db.cursor()
                    (page_size,) = cursor.execute("PRAGMA page_size").fetchone()
                    (page_count,) = cursor.execute("PRAGMA page_count").fetchone()

                    if page_size * page_count < 40960:  # less then 40 MB
                        db_mem = sqlite3.connect(":memory:")
                        db.backup(db_mem)
                        db.close()
                        db = db_mem
                    db.row_factory = sqlite3.Row
                    h = Handle(file=db, path=path)
                except (sqlite3.OperationalError, sqlite3.DatabaseError, TypeError):
                    fp = open(extended_path, "rb")
                    h = Handle(fp, path)
                except FileNotFoundError:
                    raise FileNotFoundError(f"File {path} was not found!")
            if h:
                self[regex].add(h)

    def __getitem__(self, regex: str) -> t.Union[sqlite3.Connection, IOBase]:
        try:
            files = super().__getitem__(regex)

            for num, file in enumerate(files, start=1):
                if regex not in self.logged:
                    if num == 1:
                        logger_process.info(f"\nFiles for {regex} located at:")

                    logger_process.info(f"    {file.path}")
                    self.logged.append(regex)

                if isinstance(file, IOBase):
                    file.seek(0)
            return files
        except KeyError:
            raise KeyError(f"Regex {regex} has no files opened!")

    def __delitem__(self, regex: str):
        files = self.__dict__.pop(regex, None)
        if files:
            if isinstance(files, list):
                for f in files:
                    f.close()
            else:
                files.close()
            return True
        return False

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        if key not in self:
            self[key] = self.default_factory()
        return self[key]


class FileSeekerBase(ABC):

    _all_files = []
    _directory = Path()
    _file_handles = FileHandles()

    @abstractmethod
    def search(self, filepattern_to_search, return_on_first_hit=False) -> FileList:
        """Returns a list of paths for files/folders that matched"""
        pass

    @abstractmethod
    def cleanup(self):
        """close any open handles"""
        pass

    @abstractmethod
    def build_files_list(
        self, folder: t.Optional[t.Union[str, Path]]
    ) -> t.Tuple[SubFolders, FileList]:
        """Finds files in directory"""
        pass

    @property
    def directory(self) -> Path:
        return self._directory

    @directory.setter
    def directory(self, directory: t.Union[str, Path]):
        self._directory = Path(directory)

    @property
    def all_files(self) -> list[str]:
        return self._all_files

    @all_files.setter
    def all_files(self, files: list[str]):
        self._all_files = files

    @property
    def file_handles(self) -> FileHandles:
        return self._file_handles


class FileSeekerDir(FileSeekerBase):
    def __init__(self, directory, temp_folder=None) -> None:
        self.directory = directory
        logger_log.info("Building files listing...")
        subfolders, files = self.build_files_list(directory)
        self.all_files.extend(subfolders)
        self.all_files.extend(files)
        logger_log.info(f"File listing complete - {len(self._all_files)} files")

    def build_files_list(self, folder) -> tuple:
        """Populates all paths in directory into _all_files"""

        subfolders, files = [], []

        for item in os.scandir(folder):
            if item.is_dir():
                subfolders.append(item.path)
            if item.is_file():
                files.append(item.path)

        for folder in list(subfolders):
            sf, item = self.build_files_list(folder)
            subfolders.extend(sf)
            files.extend(item)

        return subfolders, files

    def search(self, filepattern):
        return iter(fnmatch.filter(self.all_files, filepattern))

    def cleanup(self):
        pass


class FileSeekerItunes(FileSeekerBase):
    def __init__(self, directory, temp_folder):

        self.directory = directory
        self.temp_folder = temp_folder

        # logfunc('Building files listing...')
        self.build_files_list(directory)
        # logfunc(f'File listing complete - {len(self._all_files)} files')

    def build_files_list(self, folder):
        """Populates paths from Manifest.db files into _all_files"""

        directory = folder or self.directory

        db = open_sqlite_db_readonly(Path(directory) / "Manifest.db")
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT
            fileID,
            relativePath
            FROM
            Files
            WHERE
            flags=1
            """,
        )
        all_rows = cursor.fetchall()
        for row in all_rows:
            hash_filename = row[0]
            relative_path = row[1]
            self._all_files[relative_path] = hash_filename
        db.close()
        return [], []

    def search(self, filepattern, return_on_first_hit=False) -> list:
        pathlist = []
        matching_keys = fnmatch.filter(self._all_files, filepattern)
        for relative_path in matching_keys:
            hash_filename = self._all_files[relative_path]
            original_location = Path(self.directory) / hash_filename[:2] / hash_filename
            temp_location = Path(self.temp_folder) / relative_path

            temp_location.mkdir(parents=True, exist_ok=True)
            copyfile(original_location, temp_location)
            pathlist.append(temp_location)

        return iter(pathlist)


class FileSeekerTar(FileSeekerBase):
    def __init__(self, directory, temp_folder):
        self.is_gzip = directory.lower().endswith("gz")
        mode = "r:gz" if self.is_gzip else "r"
        self.tar_file = tarfile.open(directory, mode)
        self.temp_folder = temp_folder
        self.tar_file.getmembers()

    def search(self, filepattern, return_on_first_hit=False):
        for member in self.build_files_list():
            if fnmatch.fnmatch(member.name, filepattern):

                if is_platform_windows():
                    full_path = Path(f"\\\\?\\{self.temp_folder / member.name}")
                else:
                    full_path = self.temp_folder / member.name

                if not member.isdir():
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_bytes(
                        tarfile.ExFileObject(self.tar_file, member).read(),
                    )
                    os.utime(full_path, (member.mtime, member.mtime))
                yield full_path

    def cleanup(self):
        self.tar_file.close()

    @lru_cache(maxsize=5)
    def build_files_list(self):
        return self.tar_file.getmembers()


class FileSeekerZip(FileSeekerBase):
    def __init__(self, zip_file_path, temp_folder):
        self.zip_file = ZipFile(zip_file_path)
        self.name_list = self.zip_file.namelist()
        self.temp_folder = temp_folder

    def search(self, filepattern, return_on_first_hit=False):
        pathlist = []
        for member in self.name_list:
            if fnmatch.fnmatch(member, filepattern):
                try:
                    extracted_path = (
                        # already replaces illegal chars with _ when exporting
                        self.zip_file.extract(member, path=self.temp_folder)
                    )
                    pathlist.append(extracted_path)
                except Exception:
                    member = member.lstrip("/")
                    # logfunc(f'Could not write file to filesystem, path was {member} ' + str(ex))
        return iter(pathlist)

    def cleanup(self):
        self.zip_file.close()


class FileSearchProvider(UserDict):
    def __init__(self) -> None:
        self.data = {}
        self._items = 0

    def __len__(self) -> int:
        return self._items

    def register_builder(self, key, builder) -> None:
        self._items = self._items + 1
        self.data[key] = builder

    def create(self, key, **kwargs) -> FileSeekerBase:
        builder = self.data.get(key)
        if not builder:
            raise ValueError(key)
        return builder(**kwargs)


search_providers = FileSearchProvider()
search_providers.register_builder("FS", FileSeekerDir)
search_providers.register_builder("ITUNES", FileSeekerItunes)
search_providers.register_builder("TAR", FileSeekerTar)
search_providers.register_builder("ZIP", FileSeekerZip)