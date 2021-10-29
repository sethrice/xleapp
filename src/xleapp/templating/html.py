import functools
import logging
import typing as t

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import xleapp.globals as g
import xleapp.report as report


if t.TYPE_CHECKING:
    from xleapp.artifacts.abstract import Artifact
    from xleapp.report import WebIcon

logger_log = logging.getLogger("xleapp.logfile")


class Template:
    """Template decorator for HTML pages

    This is used to decorate a custom class's HTML function to change
    the Jinja2 template being used.

    Example:

        Create a new class extending from HtmlPage base class. Then,
        create a `html()` function which is decorated by this function
        which provides the template name. This function will attached
        the `template` attribute automatically which is used to return the
        HTML of the template page.

        This replaces the default report page with this template.

        class MyCustomPage(HtmlPage):
            @Template('mytemplate')
            def html(self) -> str:
                return self.template.render(renderingVals)

     Args:
         template(str): Name of Jinja template without extension.
             Must be in template folder.
    """

    def __init__(self, template: str):
        self._template = f"{template}.jinja"

    def __call__(self, func):
        @functools.wraps(func)
        def template_wrapper(cls, *args):
            if not isinstance(cls, HtmlPage):
                TypeError(
                    f"{cls.__name__!r} not {HtmlPage.__name__!r} class for"
                    f" using {__name__!r} as a decorator!",
                )
            template_j = g.app.jinja_env.get_template(self._template)
            cls.template = template_j
            return func(cls)

        return template_wrapper


@dataclass
class _HtmlPageBase:
    device: object = field(init=False)


@dataclass
class _HtmlPageDefaults:
    """HTML page defaults for the HTML page

    Attributes:
        report_folder (Path): Report folder where Artifact HTML Reports
            are saved.
        log_folder (Path): Log folder for the log output
        extraction_type (str): Type of the extraction
        processing_time (float): Float number for time it took to run
            application
        device (Device): Extracted device information object
        project (str): project name
        version (str): project version
        navigation (dict): Navigation of the HTML report
    """

    artifact: "Artifact" = field(default=None, init=False)
    report_folder: Path = field(default="", init=True)
    log_folder: Path = field(default="", init=True)
    extraction_type: str = field(default="fs", init=True)
    processing_time: float = field(default=0.0, init=True)
    navigation: dict = field(default_factory=lambda: {}, init=True)


@dataclass
class HtmlPage(ABC, _HtmlPageDefaults, _HtmlPageBase):
    def __call__(self, artifact: "Artifact"):
        self.artifact = artifact
        self.data = getattr(artifact, "data", None)
        return self

    @abstractmethod
    def html(self):
        raise NotImplementedError('HtmlPage objects must implement "html()" method!')


@dataclass
class Contributor:
    """Contributor's information displayed on main index page.

    Attributes:
        name (str): Name of Contributor
        website(str): Website of Contributor
        twitter (str): Twitter handle of the Contributor
        github (str): Github url for Contributor
    """

    name: str
    website: str = ""
    twitter: str = ""
    github: str = ""


@dataclass
class NavigationItem:
    """Navigation item for HTML report

    Attributes:
        name (str): Artifact Name
        href (str): URL of Artifact's report
        web_icon (webicons.Icon): Feather ICON for Artifact in
            the navigation list
    """

    name: str
    href: str
    web_icon: "WebIcon"

    def __str__(self) -> str:
        return f'<a class="nav-link" href="{self.href}"><span data-feather="{self.web_icon}"></span>{self.name}</a>'

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other) -> bool:
        return self.name == other.name


@dataclass
class ArtifactHtmlReport(HtmlPage):
    """Base Artifact HTML Report"""

    @Template("report_base")
    def html(self):
        """Returns HTML str of artifact report

        The :func:`@Template("report_base")` is the default Jinja2 template used for
        artifacts. Create a Jinja2 template in `report/templates` and then override
        the :func:`@html()`.

        Returns:
            str: HTML str of artifact report
        """
        return self.template.render(artifact=self.artifact, navigation=self.navigation)

    @property
    def report(self) -> bool:
        """Generates report information (html, tsv, kml, and timeline)"""
        html = self.html()
        output_file = (
            self.report_folder
            / f"{self.artifact.category} - {self.artifact.value.name}.html"
        )
        output_file.write_text(html)

        if self.artifact.processed and hasattr(self.artifact, "data"):
            options = (
                {
                    "name": self.artifact.value.name,
                    "data_list": self.data,
                    "data_headers": self.artifact.report_headers,
                },
            )
            report.save_to_db(
                report_folder=self.report_folder,
                db_type="tsv",
                options=options,
            )

            if self.artifact.kml:
                report.save_to_db(
                    report_folder=self.report_folder,
                    db_type="kml",
                    options=options,
                )

            if self.artifact.timeline:
                report.save_to_db(
                    report_folder=self.report_folder,
                    db_type="timeline",
                    options=options,
                )
        return True

    @property
    def artifact_cls(self) -> str:
        return self.artifact.cls_name