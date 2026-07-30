"""Typed models for the master profile.

The master profile is the *superset* of a career — far more than fits on any one resume. Keeping
it as structured data rather than prose is what makes it scannable: a model (or a script) can pick
roles by date, filter highlights by tag, and check which of a posting's technologies are actually
present, without re-reading paragraphs and guessing.

Every field is annotated with a :class:`Doc` description; :mod:`resume_tailor.profile.schema`
turns those into a JSON Schema so external tools get the same contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

__all__ = [
    "Contact",
    "Credential",
    "Doc",
    "Education",
    "Highlight",
    "Link",
    "Profile",
    "Project",
    "Role",
    "Technology",
    "TechnologyGroup",
    "Tenure",
]


@dataclass(frozen=True, slots=True)
class Doc:
    """Field documentation: attached with :data:`typing.Annotated`, read by the schema."""

    text: str


@dataclass(frozen=True, slots=True)
class Link:
    """A profile or portfolio URL."""

    label: Annotated[str, Doc("Human label, e.g. LinkedIn or GitHub.")]
    url: Annotated[str, Doc("Full URL, including the scheme.")]


@dataclass(frozen=True, slots=True)
class Contact:
    """Who the candidate is and how to reach them."""

    name: Annotated[str, Doc("Full name, as it should appear on the resume.")]
    headline: Annotated[
        str, Doc("Professional headline, e.g. 'Lead Software Engineer & Architect'.")
    ]
    email: Annotated[str, Doc("Primary email address.")]
    location: Annotated[str, Doc("City, ST. Add 'remote' or 'open to relocation' if true.")] = ""
    phone: Annotated[str, Doc("Phone number, formatted the way it should print.")] = ""
    work_authorization: Annotated[str, Doc("Only if worth stating, e.g. 'US citizen'.")] = ""
    links: Annotated[tuple[Link, ...], Doc("Profile and portfolio links.")] = ()


@dataclass(frozen=True, slots=True)
class Technology:
    """One tool, language, framework, platform, or practice."""

    name: Annotated[str, Doc("Canonical name, spelled the way a job posting spells it.")]
    aliases: Annotated[
        tuple[str, ...], Doc("Other spellings a screener may search for, e.g. K8s for Kubernetes.")
    ] = ()
    level: Annotated[str, Doc("One of: exposure, working, proficient, expert.")] = ""
    years: Annotated[float, Doc("Approximate years of hands-on use.")] = 0.0
    used_at: Annotated[
        tuple[str, ...], Doc("Employer ids where this was used; each must match an experience id.")
    ] = ()


@dataclass(frozen=True, slots=True)
class TechnologyGroup:
    """A named cluster of technologies — the unit a resume's Skills section prints."""

    group: Annotated[str, Doc("Group name, e.g. Frontend, Backend & Cloud, DevOps & Tools.")]
    items: Annotated[tuple[Technology, ...], Doc("Technologies in this group, strongest first.")]


@dataclass(frozen=True, slots=True)
class Highlight:
    """One accomplishment. Capture many per role — tailoring picks the relevant few."""

    text: Annotated[str, Doc("Strong verb, what was done, and the measurable outcome.")]
    label: Annotated[
        str, Doc("Short bold lead-in for the polished layout, e.g. 'Data Layer Design'.")
    ] = ""
    tags: Annotated[
        tuple[str, ...], Doc("Keywords this is evidence for, for matching against a posting.")
    ] = ()


@dataclass(frozen=True, slots=True)
class Role:
    """One title held at one employer."""

    title: Annotated[str, Doc("Job title as held.")]
    start: Annotated[str, Doc("Start date as YYYY-MM or YYYY.")]
    end: Annotated[str, Doc("End date as YYYY-MM, YYYY, or 'present'.")]
    scope: Annotated[
        str, Doc("Team size, org, remit, budget, scale — context a bullet can't carry.")
    ] = ""
    stack: Annotated[tuple[str, ...], Doc("Technologies used in this role.")] = ()
    highlights: Annotated[tuple[Highlight, ...], Doc("Accomplishments in this role.")] = ()


@dataclass(frozen=True, slots=True)
class Tenure:
    """Everything done at one employer, with each title as a separate :class:`Role`."""

    id: Annotated[
        str, Doc("Stable slug referenced by technology.used_at, e.g. charter-communications.")
    ]
    company: Annotated[str, Doc("Employer name.")]
    roles: Annotated[tuple[Role, ...], Doc("Titles held here, most recent first.")]
    location: Annotated[str, Doc("City, ST, or Remote.")] = ""
    industry: Annotated[str, Doc("Industry or domain, useful when a posting names one.")] = ""
    summary: Annotated[str, Doc("What the company or business unit does.")] = ""


@dataclass(frozen=True, slots=True)
class Education:
    """A degree, bootcamp, or program."""

    credential: Annotated[str, Doc("Degree or program name.")]
    institution: Annotated[str, Doc("School name.")]
    completed: Annotated[str, Doc("Completion date as YYYY-MM or YYYY.")] = ""
    location: Annotated[str, Doc("City, ST.")] = ""
    notes: Annotated[str, Doc("Honors, GPA if strong, relevant coursework.")] = ""


@dataclass(frozen=True, slots=True)
class Credential:
    """A certification, license, award, publication, or talk."""

    name: Annotated[str, Doc("What it is.")]
    issuer: Annotated[str, Doc("Who issued or hosted it.")] = ""
    year: Annotated[str, Doc("Year awarded, as YYYY.")] = ""
    notes: Annotated[str, Doc("Expiry, credential id, or link.")] = ""


@dataclass(frozen=True, slots=True)
class Project:
    """Side project, open-source work, or significant personal build."""

    name: Annotated[str, Doc("Project name.")]
    description: Annotated[str, Doc("What it is and what the candidate's role was.")]
    stack: Annotated[tuple[str, ...], Doc("Technologies used.")] = ()
    outcome: Annotated[str, Doc("Result, usage, or link.")] = ""


@dataclass(frozen=True, slots=True)
class Profile:
    """The complete master profile."""

    contact: Annotated[Contact, Doc("Name, headline, and contact details.")]
    summary: Annotated[str, Doc("Generic summary; tailoring rewrites a targeted one per job.")]
    experience: Annotated[tuple[Tenure, ...], Doc("Every employer, most recent first.")]
    schema_version: Annotated[int, Doc("Schema version this file targets.")] = 1
    target_roles: Annotated[
        tuple[str, ...], Doc("Job titles being aimed at; guides what to emphasise.")
    ] = ()
    technologies: Annotated[
        tuple[TechnologyGroup, ...], Doc("Every technology ever used, grouped.")
    ] = ()
    education: Annotated[tuple[Education, ...], Doc("Degrees and programs.")] = ()
    certifications: Annotated[tuple[Credential, ...], Doc("Certifications and licenses.")] = ()
    awards: Annotated[tuple[Credential, ...], Doc("Awards, publications, talks, patents.")] = ()
    projects: Annotated[tuple[Project, ...], Doc("Side projects and open-source work.")] = ()
    notes: Annotated[
        tuple[str, ...], Doc("Open questions and facts to confirm; never printed on a resume.")
    ] = ()

    def technology_names(self) -> tuple[str, ...]:
        """Every technology name and alias, for coverage checks against a posting."""
        names: list[str] = []
        for group in self.technologies:
            for item in group.items:
                names.append(item.name)
                names.extend(item.aliases)
        return tuple(names)

    def tenure_ids(self) -> frozenset[str]:
        """Every employer id, used to validate ``technology.used_at`` references."""
        return frozenset(tenure.id for tenure in self.experience)
