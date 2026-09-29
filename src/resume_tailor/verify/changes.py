"""Hold an edited profile to the one it replaced.

A model rewrites the master profile twice: once to refine a fresh draft (merging what was recorded
twice, dropping what is not a career fact, putting each accomplishment under the role it belongs
to), and again to fold in the answers the candidate gives during a review. Both rewrite the whole
file, so both are checked against the version they replace, the way a generated resume is checked
against the profile:

* **Refining adds nothing and loses nothing.** Every employer, role, date, credential, link and
  figure in the draft is still there afterwards, and nothing is there that the draft did not
  have. A technology may be dropped, because cleaning a skills list is the point, but never added
  or promoted; a role may be dropped only when another role at the same employer covers it, which
  is what merging a duplicate looks like.
* **An update adds only what the candidate said.** Every new employer, title, date, credential,
  technology, link and figure has to appear in the answers themselves, and anything removed has to
  be named in them.

Problems come back as sentences written for the model's next attempt, like verifier violations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from resume_tailor.match import build_lexicon
from resume_tailor.match.tokens import normalise
from resume_tailor.profile import format_period
from resume_tailor.verify.dates import earlier, parse_point
from resume_tailor.verify.metrics import figures_in

if TYPE_CHECKING:
    from collections.abc import Iterator

    from resume_tailor.match.lexicon import Lexicon
    from resume_tailor.profile.models import Profile, Technology

__all__ = ["check_refinement", "check_update", "describe_changes"]

_WORDS = re.compile(r"[a-z0-9]+")
_NON_DIGIT = re.compile(r"[^0-9]")
_URL_PREFIX = re.compile(r"^(?:https?://)?(?:www\.)?")
_YEAR = re.compile(r"^[0-9]{4}")
_LEGAL = frozenset(
    {"co", "company", "corp", "corporation", "gmbh", "inc", "incorporated", "limited", "llc"}
    | {"llp", "lp", "ltd", "plc"}
)
_PRESENT = "present"
_PHONE_DIGITS = 7
_PRESENT_WORDS = frozenset({"current", "currently", "now", "present", "today"})
_SHOWN = 8
"""How many names a change summary lists before it says how many more there are."""


# --- the facts a profile states -------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Role:
    company: str
    title: str
    start: str
    end: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (_company(self.company), _key(self.title), self.start, self.end)

    @property
    def label(self) -> str:
        return f"{self.title} at {self.company} ({format_period(self.start, self.end)})"


@dataclass(frozen=True, slots=True)
class _Facts:
    """Everything a change is judged on, keyed so that spelling noise does not count as change."""

    identity: dict[str, str]
    links: dict[str, str]
    employers: dict[str, str]
    roles: dict[tuple[str, str, str, str], _Role]
    credentials: dict[str, str]
    technologies: dict[str, Technology]
    forms: dict[str, str]
    """Every technology name and alias, mapped to the name of the entry that records it."""

    figures: dict[str, str]
    """Figures stated anywhere a resume can print from, as normalised value to written form."""

    note_figures: dict[str, str]
    years: frozenset[str]
    """Every year a date field states: a year written in prose is not a new claim if it is one."""

    highlights: int
    notes: tuple[str, ...]


def _facts(profile: Profile, lexicon: Lexicon) -> _Facts:
    contact = profile.contact
    roles = [
        _Role(tenure.company, role.title, role.start, role.end)
        for tenure in profile.experience
        for role in tenure.roles
    ]
    technologies: dict[str, Technology] = {}
    forms: dict[str, str] = {}
    for group in profile.technologies:
        for item in group.items:
            name = _form(item.name)
            technologies.setdefault(name, item)
            for form in (item.name, *item.aliases):
                forms.setdefault(_form(form), name)
    return _Facts(
        identity={"name": contact.name, "email": contact.email, "phone": contact.phone},
        links={_link(link.url): link.url for link in contact.links},
        employers={_company(tenure.company): tenure.company for tenure in profile.experience},
        roles={role.key: role for role in roles},
        credentials=_credentials(profile),
        technologies=technologies,
        forms=forms,
        figures=_figures(_prose(profile), lexicon),
        note_figures=_figures(iter(profile.notes), lexicon),
        years=frozenset(date[:4] for date in _dates(profile) if _YEAR.match(date)),
        highlights=sum(len(role.highlights) for t in profile.experience for role in t.roles),
        notes=profile.notes,
    )


def _credentials(profile: Profile) -> dict[str, str]:
    found = {
        f"education: {_key(entry.credential)} | {_key(entry.institution)}": (
            f"{entry.credential} ({entry.institution})"
        )
        for entry in profile.education
    }
    found |= {f"certification: {_key(item.name)}": item.name for item in profile.certifications}
    found |= {f"award: {_key(item.name)}": item.name for item in profile.awards}
    found |= {f"project: {_key(item.name)}": item.name for item in profile.projects}
    return found


def _prose(profile: Profile) -> Iterator[str]:
    """Yield every value a resume prints as a claim, rather than as a name, title or date."""
    yield from (profile.contact.headline, profile.summary, *profile.target_roles)
    for tenure in profile.experience:
        yield from (tenure.summary, tenure.industry)
        for role in tenure.roles:
            yield role.scope
            for highlight in role.highlights:
                yield from (highlight.label, highlight.text, *highlight.tags)
    yield from (entry.notes for entry in profile.education)
    yield from (item.notes for item in (*profile.certifications, *profile.awards))
    for project in profile.projects:
        yield from (project.description, project.outcome)


def _dates(profile: Profile) -> Iterator[str]:
    for tenure in profile.experience:
        for role in tenure.roles:
            yield from (role.start, role.end)
    yield from (entry.completed for entry in profile.education)
    yield from (item.year for item in (*profile.certifications, *profile.awards))


def _figures(texts: Iterator[str], lexicon: Lexicon) -> dict[str, str]:
    found: dict[str, str] = {}
    for text in texts:
        for value, raw in figures_in(text, lexicon).items():
            found.setdefault(value, raw)
    return found


# --- comparison keys ------------------------------------------------------------------------------
def _words(text: str) -> tuple[str, ...]:
    return tuple(_WORDS.findall(normalise(text).casefold()))


def _key(text: str) -> str:
    return " ".join(_words(text))


def _company(text: str) -> str:
    """Key an employer so that "Acme, Inc." and "Acme" are one company."""
    words = list(_words(text))
    while len(words) > 1 and words[-1] in _LEGAL:
        words.pop()
    return " ".join(words)


def _form(text: str) -> str:
    """Key a technology spelling. Punctuation stays: C, C++ and C# are three languages."""
    return " ".join(normalise(text).casefold().split())


def _link(url: str) -> str:
    return _URL_PREFIX.sub("", url.strip().casefold()).rstrip("/")


def _within(claim: tuple[str, ...], known: tuple[str, ...]) -> bool:
    """Report whether ``claim`` appears, in order and unbroken, inside ``known``."""
    size = len(claim)
    return bool(size) and any(
        known[index : index + size] == claim for index in range(len(known) - size + 1)
    )


_CLAIM = {"exposure": 0, "working": 1, "": 2, "proficient": 3, "expert": 4}
"""How much each level lets a resume claim, which is not the order of ``LEVELS``.

Every writer lists a technology with no level when a role shows it in use, but never one recorded
as exposure or working. So marking a blank one "exposure" narrows what can be printed, and only a
move up this scale is a claim that has to be supported.
"""


def _rank(level: str) -> int:
    return _CLAIM.get(level, _CLAIM[""])


# --- what the answers justify ---------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Said:
    """The candidate's answers, read every way a change to the profile can be justified."""

    words: tuple[str, ...]
    flat: str
    digits: str
    figures: frozenset[str]

    @classmethod
    def of(cls, answers: str, lexicon: Lexicon) -> _Said:
        return cls(
            words=_words(answers),
            flat=" ".join(normalise(answers).casefold().split()),
            digits=_NON_DIGIT.sub("", answers),
            figures=frozenset(figures_in(answers, lexicon)),
        )

    def names(self, text: str) -> bool:
        """Report whether the answers name ``text``: its words, in order."""
        return _within(_words(text), self.words)

    def states(self, value: str) -> bool:
        """Report whether the answers contain ``value`` verbatim: a name, an email, a URL.

        A phone number is compared digit for digit, because people write one five different ways.
        """
        digits = _NON_DIGIT.sub("", value)
        if len(digits) >= _PHONE_DIGITS:
            return digits in self.digits
        folded = " ".join(normalise(value).casefold().split())
        return bool(folded) and folded in self.flat

    def dates(self, value: str) -> bool:
        """Report whether the answers give this date: its year, or a word for "present"."""
        if value == _PRESENT:
            return bool(_PRESENT_WORDS & set(self.words))
        return value[:4] in self.words


# --- refinement -----------------------------------------------------------------------------------
def check_refinement(draft: Profile, refined: Profile) -> tuple[str, ...]:
    """Return every way ``refined`` adds to or loses from ``draft``; empty means acceptable."""
    lexicon = build_lexicon(draft)
    old, new = _facts(draft, lexicon), _facts(refined, lexicon)
    return (
        *_contact_kept(old, new),
        *_employers(old, new, None),
        *_roles_merged(old, new),
        *_credentials_kept(old, new),
        *_technologies(old, new, None),
        *_figures_kept(old, new),
    )


def _contact_kept(old: _Facts, new: _Facts) -> list[str]:
    problems = [
        f"changed contact.{field} from {old.identity[field]!r} to {value!r}; refining never "
        f"changes contact details"
        for field, value in new.identity.items()
        if value != old.identity[field]
    ]
    problems += [
        f"added the link {url!r}, which the draft does not have"
        for key, url in new.links.items()
        if key not in old.links
    ]
    problems += [
        f"dropped the link {url!r}; keep every link the draft has"
        for key, url in old.links.items()
        if key not in new.links
    ]
    return problems


def _roles_merged(old: _Facts, new: _Facts) -> list[str]:
    problems = [
        f"added the role {role.label}, which the draft does not have; keep every title and date "
        f"exactly as the draft records it"
        for key, role in new.roles.items()
        if key not in old.roles
    ]
    problems += [
        f"dropped the role {role.label}; keep every role, unless another role at the same "
        f"employer records the same job"
        for key, role in old.roles.items()
        if key not in new.roles and not any(_same_job(role, kept) for kept in new.roles.values())
    ]
    return problems


def _same_job(dropped: _Role, kept: _Role) -> bool:
    """Report whether ``kept`` records the job ``dropped`` did: same employer, title or time."""
    if _company(dropped.company) != _company(kept.company):
        return False
    if _key(dropped.title) == _key(kept.title):
        return True
    return not earlier(parse_point(dropped.end), parse_point(kept.start)) and not earlier(
        parse_point(kept.end), parse_point(dropped.start)
    )


def _credentials_kept(old: _Facts, new: _Facts) -> list[str]:
    problems = [
        f"added {label!r}, which the draft does not have"
        for key, label in new.credentials.items()
        if key not in old.credentials
    ]
    problems += [
        f"dropped {label!r}; keep every degree, certification, award and project"
        for key, label in old.credentials.items()
        if key not in new.credentials
    ]
    return problems


def _figures_kept(old: _Facts, new: _Facts) -> list[str]:
    problems = [
        f"introduced the figure {raw!r}, which the draft does not state"
        for value, raw in new.figures.items()
        if value not in old.figures and value not in old.years
    ]
    problems += [
        f"lost the figure {raw!r}; keep every figure the draft states (when two disagree, keep "
        f"one and put the question in notes)"
        for value, raw in old.figures.items()
        if value not in new.figures and value not in new.note_figures and value not in new.years
    ]
    return problems


# --- update from answers --------------------------------------------------------------------------
def check_update(before: Profile, after: Profile, answers: str) -> tuple[str, ...]:
    """Return every change in ``after`` that ``answers`` does not account for.

    ``answers`` is the candidate's own words only. The questions are left out on purpose: a
    question that names a technology the profile lacks must not license adding it on a "no".
    """
    lexicon = build_lexicon(before)
    old, new = _facts(before, lexicon), _facts(after, lexicon)
    said = _Said.of(answers, lexicon)
    return (
        *_contact_said(old, new, said),
        *_employers(old, new, said),
        *_roles_said(old, new, said),
        *_credentials_said(old, new, said),
        *_technologies(old, new, said),
        *_figures_said(old, new, said),
    )


def _unsaid(what: str) -> str:
    return f"{what}, which none of the answers mentions"


def _contact_said(old: _Facts, new: _Facts, said: _Said) -> list[str]:
    problems = [
        _unsaid(f"changed contact.{field} to {value!r}")
        for field, value in new.identity.items()
        if value != old.identity[field] and not said.states(value)
    ]
    problems += [
        _unsaid(f"added the link {url!r}")
        for key, url in new.links.items()
        if key not in old.links and not said.states(key)
    ]
    problems += [
        _unsaid(f"dropped the link {url!r}")
        for key, url in old.links.items()
        if key not in new.links and not said.states(key)
    ]
    return problems


def _roles_said(old: _Facts, new: _Facts, said: _Said) -> list[str]:
    problems = [
        _unsaid(f"recorded the role {role.label}")
        for key, role in new.roles.items()
        if key not in old.roles and not _role_said(role, old, said)
    ]
    problems += [
        _unsaid(f"dropped the role {role.label}")
        for key, role in old.roles.items()
        if key not in new.roles
        and not any(
            (_company(kept.company), _key(kept.title)) == key[:2] for kept in new.roles.values()
        )
        and not (said.names(role.title) or said.names(role.company))
    ]
    return problems


def _role_said(role: _Role, old: _Facts, said: _Said) -> bool:
    """Report whether every part of a new or changed role is already recorded, or was said.

    A title or date the profile already records at that employer is not new information, so a
    correction that changes only the title keeps the dates it had without the answer repeating
    them.
    """
    company = _company(role.company)
    known = [held for held in old.roles.values() if _company(held.company) == company]
    titles = {_key(held.title) for held in known}
    dates = {date for held in known for date in (held.start, held.end)}
    return (
        (company in old.employers or said.names(role.company))
        and (_key(role.title) in titles or said.names(role.title))
        and (role.start in dates or said.dates(role.start))
        and (role.end in dates or said.dates(role.end))
    )


def _credentials_said(old: _Facts, new: _Facts, said: _Said) -> list[str]:
    problems = [
        _unsaid(f"added {label!r}")
        for key, label in new.credentials.items()
        if key not in old.credentials and not said.names(label.partition(" (")[0])
    ]
    problems += [
        _unsaid(f"dropped {label!r}")
        for key, label in old.credentials.items()
        if key not in new.credentials and not said.names(label.partition(" (")[0])
    ]
    return problems


def _figures_said(old: _Facts, new: _Facts, said: _Said) -> list[str]:
    known = old.figures.keys() | old.note_figures.keys() | old.years | new.years | said.figures
    return [
        _unsaid(f"introduced the figure {raw!r}")
        for value, raw in new.figures.items()
        if value not in known
    ]


# --- shared by both -------------------------------------------------------------------------------
def _employers(old: _Facts, new: _Facts, said: _Said | None) -> list[str]:
    problems: list[str] = []
    for key, company in new.employers.items():
        if key in old.employers:
            continue
        if said is None:
            problems.append(f"added the employer {company!r}, which the draft does not have")
        elif not said.names(company):
            problems.append(_unsaid(f"added the employer {company!r}"))
    for key, company in old.employers.items():
        if key in new.employers:
            continue
        if said is None:
            problems.append(
                f"dropped the employer {company!r}; keep every employer (merge a duplicate into "
                f"one entry instead)"
            )
        elif not said.names(company):
            problems.append(_unsaid(f"dropped the employer {company!r}"))
    return problems


def _technologies(old: _Facts, new: _Facts, said: _Said | None) -> list[str]:
    """Hold technologies to the old record: nothing new, nothing promoted, unless it was said."""
    problems: list[str] = []
    for item in new.technologies.values():
        mentioned = said is not None and _said_any(item, said)
        unknown = [form for form in _spellings(item) if _form(form) not in old.forms]
        if unknown and not mentioned:
            what = f"recorded {', '.join(repr(form) for form in unknown)} as a technology"
            problems.append(
                f"{what}, which the draft does not record under any name or alias"
                if said is None
                else _unsaid(what)
            )
        previous = _counterpart(item, old)
        if previous is None or mentioned:
            continue
        rule = "refining never raises it" if said is None else "no answer says so"
        if _rank(item.level) > _rank(previous.level):
            problems.append(
                f"raised {item.name} from {previous.level or 'no level'} to "
                f"{item.level or 'no level'}; {rule}"
            )
        if item.years > previous.years:
            problems.append(
                f"raised {item.name} from {previous.years:g} to {item.years:g} years; {rule}"
            )
    if said is not None:
        problems += [
            _unsaid(f"dropped the technology {item.name!r}")
            for item in old.technologies.values()
            if _counterpart(item, new) is None and not _said_any(item, said)
        ]
    return problems


def _spellings(item: Technology) -> tuple[str, ...]:
    return (item.name, *item.aliases)


def _counterpart(item: Technology, facts: _Facts) -> Technology | None:
    """Find the entry in ``facts`` that records ``item`` under any of its spellings."""
    for form in _spellings(item):
        owner = facts.forms.get(_form(form))
        if owner is not None:
            return facts.technologies[owner]
    return None


def _said_any(item: Technology, said: _Said) -> bool:
    return any(said.names(form) for form in _spellings(item))


# --- what changed, for the person -----------------------------------------------------------------
def describe_changes(before: Profile, after: Profile) -> tuple[str, ...]:
    """Summarise, for the candidate, what an edit did to their profile: one line per kind."""
    lexicon = build_lexicon(before)
    old, new = _facts(before, lexicon), _facts(after, lexicon)
    lines: list[str] = []
    lines += [f"+ role: {role.label}" for key, role in new.roles.items() if key not in old.roles]
    lines += [f"- role: {role.label}" for key, role in old.roles.items() if key not in new.roles]
    lines += [f"+ {label}" for key, label in new.credentials.items() if key not in old.credentials]
    lines += [f"- {label}" for key, label in old.credentials.items() if key not in new.credentials]
    lines += _technology_changes(old, new)
    if new.highlights != old.highlights:
        lines.append(f"highlights: {old.highlights} → {new.highlights}")
    if before.summary != after.summary:
        lines.append("summary: rewritten")
    if before.contact.headline != after.contact.headline:
        lines.append(f"headline: {after.contact.headline}")
    resolved = [note for note in old.notes if note not in new.notes]
    added = [note for note in new.notes if note not in old.notes]
    if resolved or added:
        lines.append(f"notes: {len(old.notes)} → {len(new.notes)}")
    return tuple(lines)


def _technology_changes(old: _Facts, new: _Facts) -> list[str]:
    removed = [item.name for item in old.technologies.values() if _counterpart(item, new) is None]
    added = [item.name for item in new.technologies.values() if _counterpart(item, old) is None]
    lines: list[str] = []
    if removed or added:
        lines.append(f"technologies: {len(old.technologies)} → {len(new.technologies)}")
    if removed:
        lines.append(f"  removed: {_listed(removed)}")
    if added:
        lines.append(f"  added: {_listed(added)}")
    for item in new.technologies.values():
        previous = _counterpart(item, old)
        if previous is not None and previous.level != item.level:
            lines.append(f"  {item.name}: {previous.level or 'no level'} → {item.level or 'none'}")
    return lines


def _listed(names: list[str]) -> str:
    shown = ", ".join(names[:_SHOWN])
    more = len(names) - _SHOWN
    return f"{shown} and {more} more" if more > 0 else shown
