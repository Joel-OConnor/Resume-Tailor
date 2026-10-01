"""Compile the profile into a closed matching vocabulary.

Coverage may only ever be claimed for a string the user wrote about their own career. The lexicon
is built from ``technologies[].name`` and ``technologies[].aliases`` and nothing else — there is no
list of the world's technologies anywhere in this package.

Three properties are computed here because they gate what a match is allowed to claim:

* **tier** — how easily this form produces a false hit (``Go`` is not ``going``).
* **provenance** — is an alias a spelling of the name, or a product *category*? ``ITSM`` is a
  category, and a posting saying "ServiceNow (ITSM)" is naming a competitor of BMC Remedy.
* **evidence** — is there narrative text behind the technology, or only a ``used_at`` link?
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from resume_tailor.match.tokens import Token, stem, tokenise

if TYPE_CHECKING:
    from resume_tailor.profile.models import Profile

__all__ = ["Form", "Lexicon", "Provenance", "Tier", "admits", "alternatives", "build_lexicon"]

_PARENTHETICAL = re.compile(r"^(?P<head>[^()]+?)\s*\((?P<inner>[^()\s,]+)\)$")
_ACRONYM_MAX = 6
_SHORT_FORM_MAX = 3
_SAFE_MIN_LENGTH = 4

# Forms that are ordinary English even when capitalised. A hit needs technology framing nearby,
# because "runs on chai and code review" is a culture blurb, not a test-framework requirement.
_COMMON_WORDS = frozenset(
    {
        "agile",
        "chai",
        "mocha",
        "jest",
        "granite",
        "remedy",
        "claude",
        "node",
        "express",
        "spark",
        "go",
        "r",
        "c",
        "julia",
    }
)

# Tokens that frame a neighbouring term as a tool rather than prose. The first set reads
# naturally before the term ("written in Go"), the second after it ("Go experience").
_LEADING_FRAME = frozenset(
    {"using", "use", "used", "uses", "with", "in", "on", "via", "built", "written"}
)
_TRAILING_FRAME = frozenset(
    {
        "experience",
        "expertise",
        "proficiency",
        "familiarity",
        "knowledge",
        "stack",
        "skills",
        "technologies",
        "tooling",
        "framework",
        "frameworks",
        "library",
        "libraries",
    }
)
_TOOL_FRAME = _LEADING_FRAME | _TRAILING_FRAME
_JOINED = re.compile(r"[^/-]+")
_JS_SUFFIX = ".js"


class Tier(StrEnum):
    """How much corroboration a form needs before a hit counts."""

    SAFE = "safe"
    """Multiword, punctuated, internally capitalised, or long and unambiguous."""

    CASED = "cased"
    """An acronym or a form of three characters or fewer — casing must agree."""

    GUARDED = "guarded"
    """An ordinary English word — needs a tool frame or list context nearby."""


class Provenance(StrEnum):
    """Where a matched form sits relative to the technology's canonical name."""

    NAME = "name"
    VARIANT = "variant"
    """A respelling of the name: Postgres/PostgreSQL, Node/Node.js, K8s/Kubernetes."""

    CATEGORY = "category"
    """A product category, not a product: ITSM, CRM, SAST, containers, IaC, serverless."""


@dataclass(frozen=True, slots=True)
class Form:
    """One surface spelling of one technology."""

    technology: str
    surface: str
    tokens: tuple[str, ...]
    stems: tuple[str, ...]
    tier: Tier
    provenance: Provenance
    group: str

    @property
    def length(self) -> int:
        """Token count — longer forms win a match against shorter ones."""
        return len(self.tokens)


@dataclass(frozen=True, slots=True)
class Lexicon:
    """The compiled vocabulary plus the per-technology facts that gate a claim."""

    forms: tuple[Form, ...] = ()
    by_tokens: dict[tuple[str, ...], Form] = field(default_factory=dict)
    by_stems: dict[tuple[str, ...], Form] = field(default_factory=dict)
    max_length: int = 1
    levels: dict[str, str] = field(default_factory=dict)
    employers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    evidence: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unconfirmed: dict[str, str] = field(default_factory=dict)

    def has_evidence(self, technology: str) -> bool:
        """Report whether a highlight actually describes this technology.

        A ``used_at`` link alone says the tool was present, not that anything was accomplished
        with it — not enough to defend a must-have in an interview.
        """
        return bool(self.evidence.get(technology))


def build_lexicon(profile: Profile) -> Lexicon:
    """Compile ``profile`` into a :class:`Lexicon`."""
    forms: list[Form] = []
    levels: dict[str, str] = {}
    employers: dict[str, tuple[str, ...]] = {}

    for group in profile.technologies:
        for item in group.items:
            levels[item.name] = item.level
            employers[item.name] = item.used_at
            forms.append(_form(item.name, item.name, Provenance.NAME, group.group))
            forms += [
                _form(item.name, surface, _provenance(item.name, surface), group.group)
                for surface in _other_spellings(item.name, item.aliases)
            ]

    by_tokens: dict[tuple[str, ...], Form] = {}
    by_stems: dict[tuple[str, ...], Form] = {}
    for form in forms:
        by_tokens.setdefault(form.tokens, form)
        by_stems.setdefault(form.stems, form)

    return Lexicon(
        forms=tuple(forms),
        by_tokens=by_tokens,
        by_stems=by_stems,
        max_length=max((form.length for form in forms), default=1),
        levels=levels,
        employers=employers,
        evidence=_evidence(profile, forms, by_tokens),
        unconfirmed=_unconfirmed(profile, levels),
    )


def _other_spellings(name: str, aliases: tuple[str, ...]) -> list[str]:
    """Every spelling of a technology besides its canonical name, in order and without repeats."""
    seen = {name.casefold()}
    ordered: list[str] = []
    candidates = [
        *_expand(name),
        *aliases,
        *(part for alias in aliases for part in _expand(alias)),
    ]
    for surface in candidates:
        if (key := surface.casefold()) not in seen:
            seen.add(key)
            ordered.append(surface)
    return ordered


def _expand(surface: str) -> list[str]:
    """Split ``Expansion (ACRONYM)`` into the two halves it is also written as.

    The profile spells technologies the way a screener wants to read them — "Amazon Web Services
    (AWS)", "Artificial Intelligence (AI)" — and a resume then prints the expansion alone, the
    acronym alone, or both. All three are one claim, so registering only the joined form made the
    profile's own convention read as a fabricated skill. A parenthetical holding anything but a
    single word is left alone: "AWS (ECS, Lambda, RDS)" names other products, not other spellings.
    """
    match = _PARENTHETICAL.match(surface.strip())
    if match is None:
        return []
    return [part for part in (match["head"].strip(), match["inner"].strip()) if part]


def _form(technology: str, surface: str, provenance: Provenance, group: str) -> Form:
    tokens = tokenise(surface)
    keys = tuple(token.lower for token in tokens)
    return Form(
        technology=technology,
        surface=surface,
        tokens=keys,
        stems=tuple(stem(key) for key in keys),
        tier=_tier(surface, tokens),
        provenance=provenance,
        group=group,
    )


def _tier(surface: str, tokens: list[Token]) -> Tier:
    if len(tokens) > 1:
        return Tier.SAFE
    token = tokens[0]
    if token.lower in _COMMON_WORDS:
        return Tier.GUARDED
    short = len(surface) <= _SHORT_FORM_MAX or (token.all_caps and len(surface) <= _ACRONYM_MAX)
    if short:
        return Tier.CASED
    distinctive = token.has_inner_capital or not surface.isalpha()
    return Tier.SAFE if distinctive or len(surface) >= _SAFE_MIN_LENGTH else Tier.CASED


def _provenance(name: str, alias: str) -> Provenance:
    """Classify an alias as a respelling of the name or as a product category.

    ``Postgres``/``PostgreSQL`` and ``K8s``/``Kubernetes`` are variants. ``ITSM``/``BMC Remedy``
    and ``CRM``/``Salesforce`` are categories — matching one does not mean the posting wants the
    other, and often means it wants a competitor.

    A variant either sits inside the other spelling (Postgres, Kafka) or abbreviates it, in
    either direction: by initials (TDD, JS for JavaScript, the CI and CD of CI/CD) or as a
    numeronym (K8s). Calling those categories told the model that a posting's "K8s" might mean
    a different vendor than Kubernetes, and kept a highlight written with "K8s" from counting as
    Kubernetes evidence.
    """
    reduced_name = _reduce(name)
    reduced_alias = _reduce(alias)
    if reduced_alias in reduced_name or reduced_name in reduced_alias:
        return Provenance.VARIANT
    if _abbreviates(alias, name) or _abbreviates(name, alias):
        return Provenance.VARIANT
    return Provenance.CATEGORY


def _reduce(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


_WORD_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
_NUMERONYM = re.compile(r"^(?P<first>[a-z])(?P<count>[0-9]+)(?P<last>[a-z])$")
_MINOR_WORDS = frozenset({"a", "an", "and", "as", "for", "in", "of", "on", "the", "to", "with"})
_MIN_INITIALS = 2


def _abbreviates(short: str, long: str) -> bool:
    """Report whether ``short`` abbreviates ``long`` by its initials or as a numeronym.

    Initials are read from the words and the camel-case parts of ``long``, with and without its
    minor words: "Test-driven development" gives TDD, "JavaScript" JS, "Infrastructure as Code"
    IaC. They may match one part of a joined short form, which is how "Continuous Integration"
    abbreviates to the CI of "CI/CD". A numeronym keeps the first and last letters of a word and
    counts the letters between them, as K8s does for Kubernetes. Nothing looser counts: a
    category's acronym (ITSM, CRM, IaC) is never the initials of the product it is an alias of,
    and a variant can confirm a match a category could only qualify.
    """
    targets = {_reduce(short), *(_reduce(part) for part in short.split("/"))}
    words = _WORD_PART.findall(long)
    initials = {
        "".join(word[0] for word in words),
        "".join(word[0] for word in words if word.casefold() not in _MINOR_WORDS),
    }
    if any(len(found) >= _MIN_INITIALS and found.casefold() in targets for found in initials):
        return True
    spelled = {_reduce(long), *(word.casefold() for word in words)}
    return any(_numeronym(target, word) for target in targets for word in spelled)


def _numeronym(short: str, word: str) -> bool:
    """Report whether ``short`` is a numeronym of ``word``: "k8s" of "kubernetes"."""
    match = _NUMERONYM.match(short)
    return (
        match is not None
        and word.isalpha()
        and word[0] == match["first"]
        and word[-1] == match["last"]
        and len(word) == int(match["count"]) + 2
    )


def _evidence(
    profile: Profile, forms: list[Form], by_tokens: dict[tuple[str, ...], Form]
) -> dict[str, tuple[str, ...]]:
    """Map each technology to the highlight labels that actually describe it.

    A highlight describes a technology when it names it the way a posting would have to: as
    whole tokens, by its name or a respelling, and admitted by the form's tier. So a JavaScript
    dashboard is no evidence of Java, Google Cloud none of Go, and "helped the team go faster"
    none of Go either. A category alias never counts: running containers is not running Docker.
    Tags are the profile's own declaration of what a highlight shows, so they match in any case.
    """
    spellings = [form for form in forms if form.provenance is not Provenance.CATEGORY]
    found: dict[str, list[str]] = {form.technology: [] for form in forms}
    for tenure in profile.experience:
        for role in tenure.roles:
            for highlight in role.highlights:
                # A label is title case, so its capitals say nothing: "Worker Node Autoscaling"
                # is about Kubernetes nodes, not Node.js. Read every label word as a sentence
                # opener, which leaves only a tool frame or an acronym's shape to admit it.
                label = [
                    replace(token, sentence_initial=True) for token in tokenise(highlight.label)
                ]
                prose = [label, tokenise(highlight.text)]
                tags = [tokenise(tag) for tag in highlight.tags]
                named = {
                    form.technology
                    for form in spellings
                    if any(_names(form, tokens, admit=True) for tokens in prose)
                    or any(_names(form, tokens, admit=False) for tokens in tags)
                }
                named |= {
                    form.technology
                    for tokens in (*prose, *tags)
                    for token in tokens
                    for form in _joined(token, by_tokens)
                }
                for technology in named:
                    found[technology].append(highlight.label or highlight.text[:60])
    return {name: tuple(labels) for name, labels in found.items() if labels}


def _names(form: Form, tokens: list[Token], *, admit: bool) -> bool:
    """Report whether ``tokens`` contain ``form`` as whole tokens, tier-admitted when asked."""
    keys = [token.lower for token in tokens]
    return any(
        tuple(keys[index : index + form.length]) == form.tokens
        and (not admit or _describes(form, tokens, index))
        for index in range(len(keys) - form.length + 1)
    )


def _describes(form: Form, tokens: list[Token], index: int) -> bool:
    """Apply ``form``'s tier to a highlight, where a single letter needs a tool frame beside it.

    A lone letter is capitalised whatever it means, so its capital cannot tell the C language
    from a Series C round. Only a word that frames it can: "written in C", "a C library". The
    frame has to sit on its natural side, or "closed the Series C in March" would count.
    """
    if len(form.surface) > 1:
        return admits(form, tokens, index)
    before = tokens[index - 1].lower if index > 0 else ""
    after = tokens[index + 1].lower if index + 1 < len(tokens) else ""
    return before in _LEADING_FRAME or after in _TRAILING_FRAME


def _joined(token: Token, by_tokens: dict[tuple[str, ...], Form]) -> list[Form]:
    """Return the forms a token names by gluing them to other words.

    Prose joins a name to its neighbour: "NestJS/React/PostgreSQL", "C#/.NET", "Kafka-backed",
    "T-SQL", "React.js". A token that is itself a form is one name ("CI/CD", "PL/pgSQL"). A part
    has no neighbours to frame it, so it counts only when its shape or casing proves it on its
    own: an ordinary English word never does, and "go-live" and "Go/No-Go" say nothing of Go.
    A ".js" suffix is a frame in itself, so "Express.js" names Express. A category alias never
    counts.
    """
    if (token.lower,) in by_tokens:
        return []
    named: list[Form] = []
    for number, match in enumerate(_JOINED.finditer(token.surface)):
        part = Token(
            surface=match.group(),
            start=token.start + match.start(),
            end=token.start + match.end(),
            sentence_initial=token.sentence_initial and number == 0,
        )
        form = by_tokens.get((part.lower,))
        if form is not None and form.tier is not Tier.GUARDED and admits(form, [part], 0):
            named.append(form)
        elif form is None and part.lower.endswith(_JS_SUFFIX):
            head = by_tokens.get((part.lower.removesuffix(_JS_SUFFIX),))
            named += [head] if head is not None else []
    return [form for form in named if form.provenance is not Provenance.CATEGORY]


def alternatives(key: str, by_tokens: dict[tuple[str, ...], Form]) -> list[Form]:
    """Return the forms a slash-joined token offers: "AWS/GCP", "NestJS/React/PostgreSQL".

    "CI/CD" and "PL/pgSQL" are single names, so a token that is itself a form is never split,
    and only a SAFE part counts, since a short part like "CD" is too easily something else.
    """
    if "/" not in key or (key,) in by_tokens:
        return []
    parts = (by_tokens.get((part,)) for part in key.split("/"))
    return [form for form in parts if form is not None and form.tier is Tier.SAFE]


def _unconfirmed(profile: Profile, levels: dict[str, str]) -> dict[str, str]:
    """Map each technology named in ``notes[]`` to the note that names it.

    CLAUDE.md is explicit that anything under ``notes`` is unconfirmed and must be raised rather
    than printed. Without this, the profile's own open questions get reported as settled fact.
    """
    flagged: dict[str, str] = {}
    for note in profile.notes:
        folded = note.casefold()
        for name in levels:
            if name.casefold() in folded:
                flagged.setdefault(name, note)
    return flagged


def admits(form: Form, tokens: list[Token], index: int) -> bool:
    """Apply ``form``'s ambiguity tier to its occurrence at ``tokens[index]``."""
    if form.tier is Tier.SAFE:
        return True
    token = tokens[index]
    if form.tier is Tier.CASED:
        # Casing carries the signal: "Go" is a language, "go" is a verb. A capitalised form at
        # the very start of a sentence proves nothing, since every sentence starts capitalised.
        if form.surface.isupper():
            # An all-caps acronym is self-evidencing: "ITSM" is ITSM wherever it sits.
            return token.all_caps
        cased_ok = not form.surface[:1].isupper() or token.surface[:1].isupper()
        return cased_ok and not token.sentence_initial
    return is_tool_framed(tokens, index)


def is_tool_framed(tokens: list[Token], index: int) -> bool:
    """Report whether the token at ``index`` sits in a technology context, not prose."""
    for offset in (-1, 1):
        neighbour = index + offset
        if 0 <= neighbour < len(tokens) and tokens[neighbour].lower in _TOOL_FRAME:
            return True
    token = tokens[index]
    # Capitalisation mid-sentence is itself a frame: "Docker" is a product, "docker" is not.
    capitalised = token.surface[:1].isupper() and not token.sentence_initial
    return bool(token.all_caps or token.has_inner_capital or capitalised)
