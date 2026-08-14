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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from resume_tailor.match.tokens import Token, stem, tokenise

if TYPE_CHECKING:
    from resume_tailor.profile.models import Profile

__all__ = ["Form", "Lexicon", "Provenance", "Tier", "build_lexicon"]

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

# Tokens that frame a following term as a tool rather than prose.
_TOOL_FRAME = frozenset(
    {
        "using",
        "use",
        "used",
        "uses",
        "with",
        "in",
        "on",
        "via",
        "built",
        "written",
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
                _form(item.name, alias, _provenance(item.name, alias), group.group)
                for alias in item.aliases
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
        evidence=_evidence(profile, levels),
        unconfirmed=_unconfirmed(profile, levels),
    )


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
    """
    reduced_name = _reduce(name)
    reduced_alias = _reduce(alias)
    if reduced_alias in reduced_name or reduced_name in reduced_alias:
        return Provenance.VARIANT
    return Provenance.CATEGORY


def _reduce(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


def _evidence(profile: Profile, levels: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """Map each technology to the highlight labels that actually describe it."""
    found: dict[str, list[str]] = {name: [] for name in levels}
    for tenure in profile.experience:
        for role in tenure.roles:
            for highlight in role.highlights:
                haystack = (
                    f"{highlight.label} {highlight.text} {' '.join(highlight.tags)}".casefold()
                )
                for name in levels:
                    if _reduce(name) and name.casefold() in haystack:
                        found[name].append(highlight.label or highlight.text[:60])
    return {name: tuple(labels) for name, labels in found.items() if labels}


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
