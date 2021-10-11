# -*- coding: utf-8 -*-
"""This module contains all the functions for Artifact abstract class.

Python requires that attributes with out default values come after attributes with defaults.
The class order ABC > _AbstractArtifactDefaults > _AbstractBase ensures this is correct.

:obj:`_AbstractBase` contains all attributes without a default. Please place any extra attributes
that do not require defaults within this class. Also ensure to use `field(init=false)` for each 
attribute so they are not required when the class is first created.

:obj:`_AbstractArtifactDefaults` provides any attributes with defaults. Also, use `field(init=False)`
for each one as before.

:obj:`Artifact` is the class every artifact needs to be subclassed from.

"""

import logging
import typing as t
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import xleapp.artifacts as artifacts
from xleapp.helpers.search import Handle

from ._descriptors import FoundFiles, ReportHeaders, WebIcon

if t.TYPE_CHECKING:
    from xleapp.app import XLEAPP
    from xleapp.report._webicons import Icon


@dataclass
class _AbstractBase:
    """Base class to set any properties for
    `Artifact` Class. This properties do not
    have a default value.

    Attributes:
        category (str): Category the artifact falls into. This also is used for the area
            the artifacts appears under for the end report.
        description (str): Short description of the artifact.
        name (str): full name of the artifact.
        data (list): list of data from the `process()`.
        regex (list): search strings set by the `@Search()` decorator.
        _log (logging.Logger). Logger attached to artifact for output to log files.
    """

    description: str = field(init=False, repr=False)
    name: str = field(init=False)
    data: list = field(init=False, repr=False)
    regex: list = field(init=False, repr=False)
    _log: logging.Logger = field(init=False, repr=False)


@dataclass
class _AbstractArtifactDefaults:
    """Class to set defaults to any properties for the
    :obj:`Artifact` class.

    Attributes core, long_running_process, and selected are used
    to track artifacts internally for certain actions.

    Args:
        app (XLEAPP): attached app instance to each artifact. Default is None.
        core (bool): artifacts require to always run. Default is False.
        found (set): set of files found from a `FileSeeker`.
        hide_html_report_path_table (bool): bool to hide displaying paths
            when then report is generated. Note: Any artifact processing 10
            or more files will ignore this value.
        html_report (ArtifactHtmlReport): holds the html report object
        kml (bool): True or False to generate kml (location files) information.
            Default is False.
        long_running_process (bool): artifacts which takes an extremely long time to run
            and should be deselected by default. Default is False
        processing_time(float): Seconds of time it takes to process this artifact.
            Default is 0.0.
        report (bool): True or False. sets to generate HTML report. Default True.
        report_headers (list or tuple): headers for the report table during
            report generation.
        selected: artifacts selected to be run. Default is False.
        timeline(bool): True or False to add data to the timeline database. Default is False.
        web_icon (Icon): FeatherJS icon used for the report navgation menu. Default is `Icon.TRIANGLE`.
    """

    app: "XLEAPP" = field(init=False, repr=False, default=None)
    category: str = field(init=False, default="Unknown")
    core: bool = field(init=False, default=False)
    found: set = field(init=False, default=FoundFiles())
    kml: bool = field(init=False, default=False)
    long_running_process: bool = field(init=False, default=False)
    processed: bool = field(init=False, default=False)
    processing_time: float = field(init=False, default=float())
    report: bool = field(init=False, default=True)
    report_headers: t.Union[list, tuple] = field(init=False, default=ReportHeaders())
    selected: bool = field(init=False, default=False)
    timeline: bool = field(init=False, default=False)
    web_icon: "Icon" = field(init=False, default=WebIcon())


@dataclass
class Artifact(ABC, _AbstractArtifactDefaults, _AbstractBase):
    """Abstract class for creating Artifacts"""

    @abstractmethod
    def process(self) -> None:
        """Gets artifacts located in `files_found` params by the
        `seeker`. It saves should save the report in `report_folder`.
        """
        raise NotImplementedError(
            "Needs to implement AbastractArtifact's" "process() method!",
        )

    @contextmanager
    def context(
        self,
        regex: list[str],
        file_names_only: bool = False,
        return_on_first_hit: bool = True,
    ) -> "Artifact":
        """Creates a contaxt manager for an artifact.

        This will automatically search and add the regex and files to an artifact when
        called. You then can use `self.found` when processing the artifact.

        Example:
            This can be used with `with` blocks::

                with Artifact.context(['*/myregex*'], file_names_only=True) as artifact:
                    artifact.name = 'New Name'
                    artifact.process()


        Args:
            regex (list[str]): Globs regex expressions
            file_names_only (bool, optional): True or False. Returns a list of file
                names (true) or list of objects (false) . Defaults to False.
            return_on_first_hit (bool, optional): True or False. Returns first match on
                a regex search. Defaults to True.

        Yields:
            Iterator[Artifact]: returns self
        """
        seeker = self.app.seeker
        files = seeker.file_handles
        global_regex = files.keys()

        self.regex = regex

        for regex in self.regex:
            results = []

            if regex in global_regex:
                results = files[regex]
            else:
                try:
                    if return_on_first_hit:
                        results = {next(seeker.search(regex))}
                    else:
                        results = set(seeker.search(regex))
                except StopIteration:
                    results = None

                if bool(results):
                    files.add(regex, results, file_names_only)

            if bool(results):
                if return_on_first_hit or len(results) == 1:
                    self.found = {files[regex].copy().pop()}
                else:
                    self.found = self.found | files[regex]
        yield self

    def __enter__(self):
        return self

    @property
    def cls_name(self) -> str:
        """Returns class Name of object

        Returns:
            str: class name
        """
        return type(self).__name__

    def copyfile(self, input_file: Path, output_file: str):
        return artifacts.copyfile(
            report_folder=self.app.report_folder,
            name=self.cls_name,
            input_file=input_file,
            output_file=output_file,
        )

    def log(
        self,
        level: int = logging.INFO,
        message: object = None,
    ):
        if not hasattr(self, "_log"):
            self._log = logging.getLogger("xleapp.logfile")

        if not message:
            raise AttributeError(f"Message missing for log on {self.cls_name}!")

        self._log.log(level, msg=message)