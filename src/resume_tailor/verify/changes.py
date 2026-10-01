"""Hold an edited profile to the one it replaced.

A model rewrites the master profile twice: once to refine a fresh draft (merging what was recorded
twice, dropping what is not a career fact, putting each accomplishment under the role it belongs
to), and again to fold in the answers the candidate gives during a review. Both rewrite the whole
file, so both are checked against the version they replace, the way a generated resume is checked
against the profile:

* **Refining adds nothing and loses nothing.** Every employer, role, date, credential, link,
  contact detail and figure in the draft is still there afterwards, and nothing is there that the
  draft did not have. A technology may be dropped, because cleaning a skills list is the point,
  but never added or promoted, in the technology list or in a role's stack; a role may be dropped
  only when another role at the same employer covers it, which is what merging a duplicate looks
  like. A highlight may be reworded, merged or moved, but one that is new has to be told in the
  draft's own words for that employer.
* **An update adds only what the candidate said.** Every new employer, title, date, credential,
  technology, link and contact detail has to appear in the answers themselves, and anything
  removed has to be named in them. A figure in a field the update wrote has to be one the answers
  state or one that field already had, so a new accomplishment cannot borrow another one's
  figure; and a new highlight has to be told mostly in the answers' own words.

Problems come back as sentences written for the model's next attempt, like verifier violations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from resume_tailor.match import build_lexicon
from resume_tailor.match.tokens import normalise, stem
from resume_tailor.profile import format_period
from resume_tailor.verify.dates import PRESENT, Point, earlier, parse_point
from resume_tailor.verify.metrics import figures_in, largest_stated, magnitudes_in, prose_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from decimal import Decimal

    from resume_tailor.match.lexicon import Lexicon
    from resume_tailor.profile.models import Highlight, Profile, Technology

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

_BRIEF = 6
"""How many words of an unlabelled highlight a change summary quotes."""

_STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from", "had"}
    | {"has", "have", "i", "in", "into", "is", "it", "its", "me", "my", "of", "on", "or", "our"}
    | {"so", "than", "that", "the", "their", "them", "then", "they", "this", "to", "was", "we"}
    | {"were", "which", "while", "who", "with"}
)
"""Words that state no fact of their own, left out when a text is held to another's words."""

_DETAILS = ("location", "work_authorization")
"""Contact details written as free text, compared by their words rather than verbatim."""


# --- the facts a profile states -------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Role:
    company: str
    title: str
    start: str
    end: str
    scope: str = ""
    stack: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (_company(self.company), _key(self.title), self.start, self.end)

    @property
    def label(self) -> str:
        return f"{self.title} at {self.company} ({format_period(self.start, self.end)})"

    @property
    def name(self) -> str:
        return f"{self.title} at {self.company}"


@dataclass(frozen=True, slots=True)
class _Facts:
    """Everything a change is judged on, keyed so that spelling noise does not count as change."""

    identity: dict[str, str]
    details: dict[str, str]
    """Location and work authorization, which a candidate words as they like."""

    links: dict[str, str]
    employers: dict[str, str]
    roles: dict[tuple[str, str, str, str], _Role]
    credentials: dict[str, str]
    dated: dict[str, frozenset[str]]
    """The dates each credential records: a degree's completion, a certification's year."""

    technologies: dict[str, Technology]
    entries: tuple[Technology, ...]
    """Every technology entry as written, a spelling recorded twice included."""

    forms: dict[str, str]
    """Every technology name and alias, mapped to the name of the entry that records it."""

    projects: dict[str, tuple[str, tuple[str, ...]]]
    """Every project, keyed by its name: the name as written, and its stack."""

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
        _Role(tenure.company, role.title, role.start, role.end, role.scope, role.stack)
        for tenure in profile.experience
        for role in tenure.roles
    ]
    entries = tuple(item for group in profile.technologies for item in group.items)
    technologies: dict[str, Technology] = {}
    forms: dict[str, str] = {}
    for item in entries:
        name = _form(item.name)
        technologies.setdefault(name, item)
        for form in _spellings(item):
            forms.setdefault(_form(form), name)
    credentials, dated = _credentials(profile)
    return _Facts(
        identity={"name": contact.name, "email": contact.email, "phone": contact.phone},
        details={"location": contact.location, "work_authorization": contact.work_authorization},
        links={_link(link.url): link.url for link in contact.links},
        employers={_company(tenure.company): tenure.company for tenure in profile.experience},
        roles={role.key: role for role in roles},
        credentials=credentials,
        dated=dated,
        technologies=technologies,
        entries=entries,
        forms=forms,
        projects={
            _key(project.name): (project.name, project.stack) for project in profile.projects
        },
        figures=_figures(prose_of(profile), lexicon),
        note_figures=_figures(iter(profile.notes), lexicon),
        years=frozenset(date[:4] for date in _dates(profile) if _YEAR.match(date)),
        highlights=sum(len(role.highlights) for t in profile.experience for role in t.roles),
        notes=profile.notes,
    )


def _credentials(profile: Profile) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    """Key every degree, certification, award and project, with the dates recorded for each.

    A credential recorded twice is one key, so its dates are every date either entry gives: a
    refinement that merges the two may keep either one.
    """
    labels: dict[str, str] = {}
    dates: dict[str, set[str]] = {}
    for key, label, date in _credential_entries(profile):
        labels[key] = label
        found = dates.setdefault(key, set())
        if date:
            found.add(date)
    return labels, {key: frozenset(found) for key, found in dates.items()}


def _credential_entries(profile: Profile) -> Iterator[tuple[str, str, str]]:
    for entry in profile.education:
        yield (
            f"education: {_key(entry.credential)} | {_key(entry.institution)}",
            f"{entry.credential} ({entry.institution})",
            entry.completed,
        )
    for kind, items in (("certification", profile.certifications), ("award", profile.awards)):
        for item in items:
            yield f"{kind}: {_key(item.name)}", item.name, item.year
    for project in profile.projects:
        yield f"project: {_key(project.name)}", project.name, ""


def _dates(profile: Profile) -> Iterator[str]:
    for tenure in profile.experience:
        for role in tenure.roles:
            yield from (role.start, role.end)
    yield from (entry.completed for entry in profile.education)
    yield from (item.year for item in (*profile.certifications, *profile.awards))


def _figures(texts: Iterable[str], lexicon: Lexicon) -> dict[str, str]:
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


def _keys(texts: Iterable[str]) -> tuple[str, ...]:
    return tuple(_key(text) for text in texts)


def _content(text: str) -> frozenset[str]:
    """Return the words of ``text`` that state its facts, stemmed: "rotations" is "rotation"."""
    return frozenset(
        stem(word) for word in _words(text) if word not in _STOPWORDS and len(word) > 1
    )


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


def _mostly(words: frozenset[str], known: frozenset[str]) -> bool:
    """Report whether more than half of ``words`` are ``known``: how a new highlight is held.

    Rewording keeps most of a text's words and merging keeps all of them, while an invented
    accomplishment brings its own. The bar is a majority rather than every word, because a writer
    says "authored" where the candidate said "wrote".
    """
    return 2 * len(words & known) > len(words)


def _half(words: frozenset[str], known: frozenset[str]) -> bool:
    """Report whether at least half of ``words`` are ``known``: how a new contact detail is held.

    A detail is a few words, and a writer adds the state to a city the candidate named ("Denver"
    becomes "Denver, CO"), so half is enough; one invented word on its own is still caught.
    """
    return 2 * len(words & known) >= len(words)


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
    content: frozenset[str]
    """The answers' words that state facts, stemmed, which a new highlight is held to."""

    largest: Decimal
    """The largest quantity the answers state, which bounds a size an update writes in words."""

    @classmethod
    def of(cls, answers: str, lexicon: Lexicon) -> _Said:
        return cls(
            words=_words(answers),
            flat=" ".join(normalise(answers).casefold().split()),
            digits=_NON_DIGIT.sub("", answers),
            figures=frozenset(figures_in(answers, lexicon)),
            content=_content(answers),
            largest=largest_stated([answers]),
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
        *_headline_kept(draft, refined),
        *_employers(old, new, None),
        *_roles_merged(old, new),
        *_credentials_kept(old, new),
        *_technologies(old, new, None),
        *_stacks_kept(draft, old, new),
        *_figures_kept(old, new),
        *_sizes_kept(draft, refined, lexicon),
        *_highlights_kept(draft, refined),
    )


def _contact_kept(old: _Facts, new: _Facts) -> list[str]:
    problems = [
        f"changed contact.{field} from {old.identity[field]!r} to {value!r}; refining never "
        f"changes contact details"
        for field, value in new.identity.items()
        if value != old.identity[field]
    ]
    problems += [
        f"changed contact.{field} from {old.details[field]!r} to {value!r}; refining never "
        f"changes contact details"
        for field, value in new.details.items()
        if _key(value) != _key(old.details[field])
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


def _headline_kept(draft: Profile, refined: Profile) -> list[str]:
    """Hold a reworded headline to the draft's words: it may agree with the roles, not outrank them.

    Refining may bring the headline in line with the experience, so it is not held verbatim, but
    the words it adds have to be words the draft already uses: "Senior Backend Engineer" may
    become "Senior Backend Engineer, Payments", never "Principal Engineer".
    """
    added = _content(refined.contact.headline) - _content(draft.contact.headline)
    if not added or _half(added, _vocabulary(draft)):
        return []
    return [
        (
            f"changed contact.headline to {refined.contact.headline!r}, which the draft's titles "
            f"and text do not support; keep the headline to what the draft records"
        )
    ]


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
    """Report whether ``kept`` records the job ``dropped`` did: same employer, title or time.

    Under another title, ``kept`` has to cover every month ``dropped`` could mean. Sharing some
    time is not enough, because a role that runs a month past the start of the next one is the
    step before a promotion, not a duplicate of it. So a year given alone runs January to
    December in ``dropped``, but only December to January in ``kept``. The exception is a copy
    written to the year, as an old resume writes it: ``dropped`` starting and ending in the
    years ``kept`` does.
    """
    if _company(dropped.company) != _company(kept.company):
        return False
    if _key(dropped.title) == _key(kept.title):
        return True
    start, end = parse_point(dropped.start), parse_point(dropped.end)
    first, last = parse_point(kept.start), parse_point(kept.end)
    if (start.year, end.year) != (first.year, last.year):
        start, end = _in_month(start, 1), _in_month(end, 12)
    return not earlier(start, _in_month(first, 12)) and not earlier(_in_month(last, 1), end)


def _in_month(point: Point, month: int) -> Point:
    """Put a year given alone in ``month``; a point with its month, or present, stays as it is."""
    return point if point.month or point == PRESENT else Point(point.year, month)


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
    for key, label in new.credentials.items():
        if key in old.credentials:
            problems += _dates_kept(label, old.dated[key], new.dated[key])
    return problems


def _dates_kept(label: str, before: frozenset[str], after: frozenset[str]) -> list[str]:
    """Hold a credential's dates to the draft's: none changed, and no year of them lost.

    A credential can hold more than one date (a certification renewed, an award won twice), so
    losing one of them is a loss even while another remains. A date that changed is reported as
    the change.
    """
    recorded = _dates_listed(before)
    if changed := sorted(after - before):
        return [
            f"changed the date of {label!r} from {recorded} to {date}; keep every date exactly "
            f"as the draft records it"
            if before
            else f"gave {label!r} the date {date}, which the draft does not record for it"
            for date in changed
        ]
    return [
        f"dropped the date {date} from {label!r}; keep every date the draft records"
        for date in _lost(before, after)
    ]


def _lost(before: frozenset[str], after: frozenset[str]) -> list[str]:
    """Return each date in ``before`` whose year ``after`` no longer records.

    Years are compared, not the dates as written, so merging a "2016-05" into its "2016" twin
    loses nothing.
    """
    years = {date[:4] for date in after}
    return sorted(date for date in before if date[:4] not in years)


def _stacks_kept(draft: Profile, old: _Facts, new: _Facts) -> list[str]:
    """Hold every stack to technologies the draft records: in its list, a stack, or its text.

    A refinement may put a technology under the role whose work used it, so one the draft names
    anywhere is not new; one it never names is, and a stack is where a resume prints it from.
    """
    known = set(old.forms) | {_form(item) for item in _stack_items(old)}
    texts = [_words(text) for text in _texts(draft)]
    return [
        f"added {item!r} to the stack of {where}, which the draft does not record anywhere"
        for where, stack in _stacks(new)
        for item in stack
        if _form(item) not in known and not any(_within(_words(item), text) for text in texts)
    ]


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


def _sizes_kept(draft: Profile, refined: Profile, lexicon: Lexicon) -> list[str]:
    """Hold a size in words ("millions of users") to the largest quantity the draft states."""
    largest = largest_stated(prose_of(draft))
    return [
        f"claimed {raw!r}, a size larger than any figure the draft states"
        for text in prose_of(refined)
        for raw, least in magnitudes_in(text, lexicon).items()
        if least > largest
    ]


def _highlights_kept(draft: Profile, refined: Profile) -> list[str]:
    """Hold every highlight the draft does not have word for word to the draft's own words.

    Rewording, merging and moving a highlight keep most of its words, and a technology the draft
    lists may become the accomplishment it really was. An accomplishment the draft never told is
    told in words the draft does not use at that employer, and that is what is reported.
    """
    had = {_key(highlight.text) for _, highlight in _highlights(draft)}
    known = {company: _vocabulary(draft, company) for company in _employer_keys(refined)}
    return [
        f"added the highlight {_brief(highlight)}, which nothing the draft records at that "
        f"employer supports; keep each highlight to what the draft states"
        for company, highlight in _highlights(refined)
        if _key(highlight.text) not in had and not _mostly(_content(highlight.text), known[company])
    ]


# --- update from answers --------------------------------------------------------------------------
def check_update(before: Profile, after: Profile, answers: str) -> tuple[str, ...]:
    """Return every change in ``after`` that ``answers`` does not account for.

    ``answers`` is what the answers establish, as :func:`resume_tailor.review.questions.said`
    puts it: the candidate's own words, plus the question each one accepts. A question the answer
    declines is left out, so a "no" to a question that names a technology the profile lacks
    cannot license adding it.
    """
    lexicon = build_lexicon(before)
    old, new = _facts(before, lexicon), _facts(after, lexicon)
    said = _Said.of(answers, lexicon)
    return (
        *_contact_said(old, new, said),
        *_details_said(before, after, said),
        *_employers(old, new, said),
        *_roles_said(old, new, said),
        *_credentials_said(old, new, said),
        *_technologies(old, new, said),
        *_stacks_said(old, new, said),
        *_fields_said(before, after, said, lexicon),
        *_scopes_said(old, new, said, lexicon),
        *_highlights_said(before, after, said, lexicon),
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


def _details_said(before: Profile, after: Profile, said: _Said) -> list[str]:
    """Hold the words an update adds to a free-text contact detail to the answers' words.

    Location, work authorization and the headline are written in the candidate's own phrasing,
    so they are not compared verbatim. What the update adds to one has to be in the answers: an
    answer about a salary cannot bring "active Top Secret clearance" with it.
    """
    problems: list[str] = []
    for field in ("headline", *_DETAILS):
        was, now = getattr(before.contact, field), getattr(after.contact, field)
        added = _content(now) - _content(was)
        if added and not _half(added, said.content):
            problems.append(_unsaid(f"changed contact.{field} to {now!r}"))
    return problems


def _roles_said(old: _Facts, new: _Facts, said: _Said) -> list[str]:
    """Hold every new or changed role to the answers, and account for every role that went.

    A role that went is accounted for when the answers name it, or when a changed role took its
    place: its title with other dates, or its dates under another title. Each changed role takes
    the place of one role at most, so a stint that goes beside another with the same title is
    still a removal to name.
    """
    changed = [role for key, role in new.roles.items() if key not in old.roles]
    problems = [
        _unsaid(f"recorded the role {role.label}")
        for role in changed
        if not _role_said(role, old, new, said)
    ]
    for key, role in old.roles.items():
        if key in new.roles:
            continue
        heir = next((held for held in changed if _succeeds(held, role)), None)
        if heir is not None:
            changed.remove(heir)
        elif not (said.names(role.title) or said.names(role.company)):
            problems.append(_unsaid(f"dropped the role {role.label}"))
    return problems


def _succeeds(role: _Role, gone: _Role) -> bool:
    """Report whether ``role`` is ``gone`` corrected: same employer, and same title or dates."""
    return _company(role.company) == _company(gone.company) and (
        _key(role.title) == _key(gone.title) or (role.start, role.end) == (gone.start, gone.end)
    )


def _predecessor(role: _Role, old: _Facts, new: _Facts) -> _Role | None:
    """Return the role ``role`` was before the edit: itself, or the one it corrected."""
    if role.key in old.roles:
        return old.roles[role.key]
    return next(
        (gone for key, gone in old.roles.items() if key not in new.roles and _succeeds(role, gone)),
        None,
    )


def _role_said(role: _Role, old: _Facts, new: _Facts, said: _Said) -> bool:
    """Report whether every part of a new or changed role is already recorded, or was said.

    A date the role already had is not new information, so a correction that changes only the
    title or one date keeps the others without the answer repeating them. The role could have
    been an old role there with its title or, under a title new to that employer, any role the
    update replaced. Under a title held elsewhere there, a replaced role counts only when the
    role keeps both of its dates, which is a correction of the title alone.

    Each of those roles is judged on its own: the start and end have to be one role's, or be
    said. Pooling their dates would let "Principal Engineer" move back over the years spent as
    "Engineer", or join two stints with one title into a single run through the years between.
    """
    company = _company(role.company)
    titled = said.names(role.title)
    known = [held for held in old.roles.values() if _company(held.company) == company]
    same = [held for held in known if _key(held.title) == _key(role.title)]
    replaced = [
        held
        for held in known
        if held.key not in new.roles
        and (not same or (held.start, held.end) == (role.start, role.end))
    ]
    kept = any(
        (titled or _key(held.title) == _key(role.title))
        and (held.start == role.start or said.dates(role.start))
        and (held.end == role.end or said.dates(role.end))
        for held in (*same, *replaced)
    )
    return (company in old.employers or said.names(role.company)) and (
        kept or (titled and said.dates(role.start) and said.dates(role.end))
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
    for key, label in new.credentials.items():
        known = old.dated[key] if key in old.credentials else _renamed_dates(key, old, new)
        changed = sorted(new.dated[key] - known)
        problems += [
            _unsaid(f"recorded {date} as the date of {label!r}")
            for date in changed
            if not said.dates(date)
        ]
        if not changed and not said.names(label.partition(" (")[0]):
            problems += [
                _unsaid(f"dropped the date {date} from {label!r}")
                for date in _lost(known, new.dated[key])
            ]
    return problems


def _renamed_dates(key: str, old: _Facts, new: _Facts) -> frozenset[str]:
    """Return the dates a new credential keeps from the one it renames, if it renames one.

    A credential the answer renames is a new key, and its date comes with it. A rename puts one
    credential in place of one of the same kind, keeping most of its words: "Fellow of the Royal
    Analytical Society" for "Fellow of the Analytical Society". One dropped beside an unrelated
    one added is not a rename, and the new one's date has to be said.
    """
    kind = key[: key.index(":") + 1]
    dropped = [gone for gone in old.dated if gone not in new.dated and gone.startswith(kind)]
    added = [fresh for fresh in new.dated if fresh not in old.dated and fresh.startswith(kind)]
    origins = [gone for gone in dropped if _renames(gone, key)]
    if len(origins) != 1 or [fresh for fresh in added if _renames(origins[0], fresh)] != [key]:
        return frozenset()
    return old.dated[origins[0]]


def _renames(before: str, after: str) -> bool:
    """Report whether credential key ``after`` keeps most of the words of ``before``."""
    words = set(_WORDS.findall(before.partition(":")[2]))
    return 2 * len(words & set(_WORDS.findall(after.partition(":")[2]))) > len(words)


def _stacks_said(old: _Facts, new: _Facts, said: _Said) -> list[str]:
    """Hold every technology an update adds to a role's or a project's stack to the answers.

    A stack says the technology was used there, which a resume then prints under that role, so
    putting one in a stack is a claim even when the technology list already has it. Respelling
    an item ("Kafka" for "Apache Kafka") adds nothing.
    """
    problems: list[str] = []
    for role in new.roles.values():
        previous = _predecessor(role, old, new)
        had = _identities(previous.stack if previous else (), old, new)
        problems += [
            _unsaid(f"added {item!r} to the stack of {role.name}")
            for item in role.stack
            if _identity(item, old, new) not in had and not _tech_said(item, old, new, said)
        ]
    for key, (name, stack) in new.projects.items():
        had = _identities(old.projects.get(key, (name, ()))[1], old, new)
        problems += [
            _unsaid(f"added {item!r} to the stack of {name}")
            for item in stack
            if _identity(item, old, new) not in had and not _tech_said(item, old, new, said)
        ]
    return problems


def _identity(item: str, *facts: _Facts) -> str:
    """Key a stack item by the technology entry that records it, so a respelling is no change."""
    form = _form(item)
    return next((every.forms[form] for every in facts if form in every.forms), form)


def _identities(stack: Iterable[str], *facts: _Facts) -> frozenset[str]:
    return frozenset(_identity(item, *facts) for item in stack)


def _tech_said(item: str, old: _Facts, new: _Facts, said: _Said) -> bool:
    """Report whether the answers name a stack item, under its own spelling or its entry's."""
    if said.names(item):
        return True
    entries = [
        facts.technologies[name]
        for facts in (old, new)
        if (name := _identity(item, facts)) in facts.technologies
    ]
    return any(_said_any(entry, said) for entry in entries)


def _fields_said(before: Profile, after: Profile, said: _Said, lexicon: Lexicon) -> list[str]:
    """Hold every figure in a field the update wrote to the answers, or to that field before it.

    A figure that moved from another field is a figure the answers never gave this one: a new
    accomplishment carrying another one's 38%, or a role's start year where the answer said 2022.
    Highlights and scopes are matched to what they were by :func:`_highlights_said` and
    :func:`_scopes_said`; every other field is found by its place. A field whose place went
    (a credential the answer renamed) may carry its text, unchanged, to its new place.
    """
    was = {place: texts for place, _, texts in _fields(before)}
    now = {place: (where, texts) for place, where, texts in _fields(after)}
    moved = {_keys(texts) for place, texts in was.items() if place not in now}
    problems: list[str] = []
    for place, (where, texts) in now.items():
        if _keys(texts) not in moved:
            problems += _figures_said(where, texts, was.get(place, ()), said, lexicon)
    return problems


def _scopes_said(old: _Facts, new: _Facts, said: _Said, lexicon: Lexicon) -> list[str]:
    """Hold every figure in a role's scope to the answers, or to that role's scope before.

    A role the answer corrected keeps its scope; so does one whose title and dates both changed,
    as long as its scope is the one a role that went had.
    """
    moved = {_key(role.scope) for key, role in old.roles.items() if key not in new.roles}
    problems: list[str] = []
    for role in new.roles.values():
        if _key(role.scope) in moved:
            continue
        previous = _predecessor(role, old, new)
        was = (previous.scope,) if previous else ()
        where = f"the scope of {role.name}"
        problems += _figures_said(where, (role.scope,), was, said, lexicon)
    return problems


def _highlights_said(before: Profile, after: Profile, said: _Said, lexicon: Lexicon) -> list[str]:
    """Hold every highlight the update wrote: its figures, and its words when it is new.

    A rewritten highlight may keep its own figures and add the answers'. A new one has only the
    answers to draw on, and has to be told mostly in their words: an answer about on-call pages
    cannot become an accomplishment about fraud detection.
    """
    by_text = {_key(highlight.text): highlight for _, highlight in _highlights(before)}
    pairs, _ = _pairs(before, after)
    rewritten = {pair.new: pair.old for pair in pairs}
    problems: list[str] = []
    for _, highlight in _highlights(after):
        previous = by_text.get(_key(highlight.text)) or rewritten.get(highlight)
        where = f"the highlight {_brief(highlight)}"
        was = _highlight_texts(previous) if previous else ()
        problems += _figures_said(where, _highlight_texts(highlight), was, said, lexicon)
        if previous is None and not _mostly(_content(highlight.text), said.content):
            problems.append(_unsaid(f"added the highlight {_brief(highlight)}"))
    return problems


def _figures_said(
    where: str, texts: Sequence[str], previous: Sequence[str], said: _Said, lexicon: Lexicon
) -> list[str]:
    """Report each figure in ``texts`` that neither the answers nor ``previous`` state.

    A size in words ("millions of users") may be no larger than a quantity either of them states.
    """
    if _keys(texts) == _keys(previous):
        return []
    known = said.figures | _figures(previous, lexicon).keys()
    problems = [
        _unsaid(f"introduced the figure {raw!r} in {where}")
        for value, raw in _figures(texts, lexicon).items()
        if value not in known
    ]
    largest = max(said.largest, largest_stated(previous))
    problems += [
        f"claimed {raw!r} in {where}, a size larger than anything the answers state"
        for text in texts
        for raw, least in magnitudes_in(text, lexicon).items()
        if least > largest
    ]
    return problems


def _fields(profile: Profile) -> Iterator[tuple[tuple[str, str], str, tuple[str, ...]]]:
    """Yield every prose field but highlights and scopes: its place, its name, and its text."""
    yield ("headline", ""), "the headline", (profile.contact.headline,)
    yield ("summary", ""), "the summary", (profile.summary,)
    yield ("target roles", ""), "the target roles", profile.target_roles
    for tenure in profile.experience:
        texts = (tenure.summary, tenure.industry)
        yield ("employer", _company(tenure.company)), f"the description of {tenure.company}", texts
    for key, label, notes in _notes(profile):
        yield ("notes", key), f"the notes on {label!r}", (notes,)
    for project in profile.projects:
        texts = (project.description, project.outcome)
        yield ("project", _key(project.name)), f"the project {project.name!r}", texts


def _notes(profile: Profile) -> Iterator[tuple[str, str, str]]:
    for entry in profile.education:
        yield _key(f"{entry.credential} {entry.institution}"), entry.credential, entry.notes
    for item in (*profile.certifications, *profile.awards):
        yield _key(item.name), item.name, item.notes


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
    """Hold technologies to the old record: nothing new, nothing promoted, unless it was said.

    An entry is held to the most any entry sharing one of its spellings claimed, so merging the
    draft's "PostgreSQL" (no level) and "Postgres" (expert) into one entry may keep "expert"
    under either name.
    """
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
        ceiling = _ceiling(item, old)
        if ceiling is None or mentioned:
            continue
        level, years = ceiling
        rule = "refining never raises it" if said is None else "no answer says so"
        if _rank(item.level) > _rank(level):
            problems.append(
                f"raised {item.name} from {level or 'no level'} to {item.level or 'no level'}; "
                f"{rule}"
            )
        if item.years > years:
            problems.append(f"raised {item.name} from {years:g} to {item.years:g} years; {rule}")
    if said is not None:
        problems += [
            _unsaid(f"dropped the technology {item.name!r}")
            for item in old.technologies.values()
            if _counterpart(item, new) is None and not _said_any(item, said)
        ]
    return problems


def _ceiling(item: Technology, facts: _Facts) -> tuple[str, float] | None:
    """Return the highest level and years any entry sharing a spelling with ``item`` records."""
    spellings = {_form(form) for form in _spellings(item)}
    matches = [
        entry for entry in facts.entries if spellings & {_form(form) for form in _spellings(entry)}
    ]
    if not matches:
        return None
    level = max((entry.level for entry in matches), key=_rank)
    return level, max(entry.years for entry in matches)


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


def _dates_listed(dates: frozenset[str]) -> str:
    return " or ".join(sorted(dates)) or "no date"


def _stacks(facts: _Facts) -> Iterator[tuple[str, tuple[str, ...]]]:
    """Yield every stack: each role's, named by the role, and each project's."""
    for role in facts.roles.values():
        yield role.label, role.stack
    yield from facts.projects.values()


def _stack_items(facts: _Facts) -> Iterator[str]:
    for _, stack in _stacks(facts):
        yield from stack


def _texts(profile: Profile) -> Iterator[str]:
    """Yield every text the profile records about the career, notes aside."""
    yield from prose_of(profile)
    for tenure in profile.experience:
        yield from (tenure.company, tenure.location)
        for role in tenure.roles:
            yield from (role.title, *role.stack)
    for group in profile.technologies:
        for item in group.items:
            yield from _spellings(item)
    for project in profile.projects:
        yield from (project.name, *project.stack)


def _employer_keys(profile: Profile) -> frozenset[str]:
    return frozenset(_company(tenure.company) for tenure in profile.experience)


def _vocabulary(profile: Profile, company: str | None = None) -> frozenset[str]:
    """Return the words the profile uses, at one employer when ``company`` names one.

    Every technology's spellings count wherever the words are wanted, because refining may turn
    a technology that was really an accomplishment ("Scheduler rewrite") into the highlight.
    """
    texts = [
        spelling
        for group in profile.technologies
        for item in group.items
        for spelling in _spellings(item)
    ]
    if company is None:
        texts += _texts(profile)
    for tenure in profile.experience:
        if company is None or _company(tenure.company) != company:
            continue
        texts += (tenure.company, tenure.industry, tenure.summary, tenure.location)
        for role in tenure.roles:
            texts += (role.title, role.scope, *role.stack)
            for highlight in role.highlights:
                texts += _highlight_texts(highlight)
    return frozenset(word for text in texts for word in _content(text))


# --- what changed, for the person -----------------------------------------------------------------
def describe_changes(before: Profile, after: Profile) -> tuple[str, ...]:
    """Summarise, for the candidate, what an edit did to their profile: one line per kind."""
    lexicon = build_lexicon(before)
    old, new = _facts(before, lexicon), _facts(after, lexicon)
    lines = _contact_changes(old, new)
    lines += [f"+ role: {role.label}" for key, role in new.roles.items() if key not in old.roles]
    lines += [f"- role: {role.label}" for key, role in old.roles.items() if key not in new.roles]
    lines += _role_changes(old, new)
    lines += [f"+ {label}" for key, label in new.credentials.items() if key not in old.credentials]
    lines += [f"- {label}" for key, label in old.credentials.items() if key not in new.credentials]
    lines += [
        f"{label}: {_dates_listed(old.dated[key])} → {_dates_listed(new.dated[key])}"
        for key, label in new.credentials.items()
        if key in old.credentials and old.dated[key] != new.dated[key]
    ]
    lines += _technology_changes(old, new)
    if new.highlights != old.highlights:
        lines.append(f"highlights: {old.highlights} → {new.highlights}")
    removed, added, edited = _highlight_changes(before, after)
    for kind, names in (("removed", removed), ("added", added), ("edited", edited)):
        if names:
            lines.append(f"highlights {kind}: {_listed(names)}")
    if before.summary != after.summary:
        lines.append("summary: rewritten")
    if before.contact.headline != after.contact.headline:
        lines.append(f"headline: {after.contact.headline}")
    if before.target_roles != after.target_roles:
        lines.append(f"target roles: {', '.join(after.target_roles) or 'none'}")
    resolved = [note for note in old.notes if note not in new.notes]
    added = [note for note in new.notes if note not in old.notes]
    if resolved or added:
        lines.append(f"notes: {len(old.notes)} → {len(new.notes)}")
    return tuple(lines)


def _contact_changes(old: _Facts, new: _Facts) -> list[str]:
    """Name every contact detail an edit changed, and every link it added or removed."""
    values = {**old.identity, **old.details}
    lines = [
        f"{field.replace('_', ' ')}: {value or 'removed'}"
        for field, value in {**new.identity, **new.details}.items()
        if value != values[field]
    ]
    lines += [f"+ link: {url}" for key, url in new.links.items() if key not in old.links]
    lines += [f"- link: {url}" for key, url in old.links.items() if key not in new.links]
    return lines


def _role_changes(old: _Facts, new: _Facts) -> list[str]:
    """Name what an edit changed inside a role it kept: its stack and its scope."""
    lines: list[str] = []
    for role in new.roles.values():
        previous = _predecessor(role, old, new)
        if previous is None:
            continue
        lines += _stack_change(role.name, previous.stack, role.stack, old, new)
        if _key(previous.scope) != _key(role.scope):
            lines.append(f"{role.name}: scope: {role.scope or 'removed'}")
    for key, (name, stack) in new.projects.items():
        if key in old.projects:
            lines += _stack_change(name, old.projects[key][1], stack, old, new)
    return lines


def _stack_change(
    name: str, was: Sequence[str], now: Sequence[str], old: _Facts, new: _Facts
) -> list[str]:
    before, after = _identities(was, old, new), _identities(now, old, new)
    added = [item for item in now if _identity(item, old, new) not in before]
    removed = [item for item in was if _identity(item, old, new) not in after]
    lines = [f"{name}: stack + {_listed(added)}"] if added else []
    return lines + ([f"{name}: stack - {_listed(removed)}"] if removed else [])


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
        if previous is None:
            continue
        if previous.level != item.level:
            lines.append(f"  {item.name}: {previous.level or 'no level'} → {item.level or 'none'}")
        if previous.years != item.years:
            lines.append(f"  {item.name}: {previous.years:g} → {item.years:g} years")
        lines += _used_at_change(item.name, previous.used_at, item.used_at)
    return lines


def _used_at_change(name: str, was: Sequence[str], now: Sequence[str]) -> list[str]:
    added = [employer for employer in now if employer not in was]
    removed = [employer for employer in was if employer not in now]
    lines = [f"  {name}: used at + {_listed(added)}"] if added else []
    return lines + ([f"  {name}: used at - {_listed(removed)}"] if removed else [])


@dataclass(frozen=True, slots=True)
class _Pair:
    """A highlight an edit wrote, and the one it replaced, when it replaced one."""

    new: Highlight
    old: Highlight | None


def _pairs(before: Profile, after: Profile) -> tuple[list[_Pair], list[Highlight]]:
    """Pair each highlight an edit added or rewrote with the one it replaced, leaving out moves.

    A highlight has no id, so a new text is paired with a text the edit removed at the same
    employer: by label when there is one to match, then in order among texts that share most of
    their words. Returns the pairs, and the old highlights paired with nothing, which went.
    """
    old, new = _highlights(before), _highlights(after)
    still = {_key(highlight.text) for _, highlight in new}
    had = {_key(highlight.text) for _, highlight in old}
    gone = [pair for pair in old if _key(pair[1].text) not in still]
    fresh = [pair for pair in new if _key(pair[1].text) not in had]
    replaced: dict[int, Highlight] = {}
    for by_label in (True, False):
        for index, (company, highlight) in enumerate(fresh):
            label = _key(highlight.label)
            if index in replaced or (by_label and not label):
                continue
            match = next(
                (
                    pair
                    for pair in gone
                    if pair[0] == company
                    and (
                        _key(pair[1].label) == label
                        if by_label
                        else _alike(pair[1].text, highlight.text)
                    )
                ),
                None,
            )
            if match is not None:
                gone.remove(match)
                replaced[index] = match[1]
    pairs = [_Pair(highlight, replaced.get(index)) for index, (_, highlight) in enumerate(fresh)]
    return pairs, [highlight for _, highlight in gone]


def _highlight_changes(before: Profile, after: Profile) -> tuple[list[str], list[str], list[str]]:
    """Name the highlights an edit removed, added and edited, leaving out any it only moved."""
    pairs, gone = _pairs(before, after)
    return (
        [_brief(highlight) for highlight in gone],
        [_brief(pair.new) for pair in pairs if pair.old is None],
        [_brief(pair.new) for pair in pairs if pair.old is not None],
    )


def _alike(first: str, second: str) -> bool:
    """Report whether two texts share at least half the words of the shorter one."""
    one, two = set(_words(first)), set(_words(second))
    shared = one & two
    return bool(shared) and 2 * len(shared) >= min(len(one), len(two))


def _highlights(profile: Profile) -> list[tuple[str, Highlight]]:
    return [
        (_company(tenure.company), highlight)
        for tenure in profile.experience
        for role in tenure.roles
        for highlight in role.highlights
    ]


def _highlight_texts(highlight: Highlight) -> tuple[str, ...]:
    return (highlight.label, highlight.text, *highlight.tags)


def _brief(highlight: Highlight) -> str:
    """Name a highlight in a line: its label, or the first few words of its text."""
    if highlight.label:
        return highlight.label
    words = highlight.text.split()
    more = "…" if len(words) > _BRIEF else ""
    return f'"{" ".join(words[:_BRIEF])}{more}"'


def _listed(names: Sequence[str]) -> str:
    shown = ", ".join(names[:_SHOWN])
    more = len(names) - _SHOWN
    return f"{shown} and {more} more" if more > 0 else shown
