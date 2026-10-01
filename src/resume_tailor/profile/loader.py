"""Read and validate ``output/master-profile.yaml`` into typed models.

Validation is generic: it walks the dataclass type hints, so the models are the only place a
field is ever declared. Errors carry the path to the offending value (``experience[0].roles[1]``)
because a 400-line profile is no fun to bisect by hand.
"""

from __future__ import annotations

import dataclasses
import datetime
import math
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Annotated, Any, get_args, get_origin, get_type_hints, override

import yaml

from resume_tailor.errors import ProfileError
from resume_tailor.paths import PROFILE_PATH
from resume_tailor.profile.models import Profile, Technology, Tenure

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DATE_BODY",
    "DEFAULT_PROFILE_PATH",
    "LEVELS",
    "PRESENT",
    "SLUG_PATTERN",
    "YEAR_BODY",
    "load",
    "load_mapping",
    "loads",
]

DEFAULT_PROFILE_PATH = PROFILE_PATH
LEVELS = ("exposure", "working", "proficient", "expert")

# [0-9] rather than \d: \d also matches Devanagari and other non-ASCII digits, which pass
# validation and then break date ordering, rendering, and the mirrored JSON Schema pattern.
# The bodies are public because the schema composes its patterns from them, so the two can
# never accept different values.
DATE_BODY = r"[0-9]{4}|[0-9]{4}-(?:0[1-9]|1[0-2])"
YEAR_BODY = r"[0-9]{4}"
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
PRESENT = "present"
_DATE = re.compile(rf"^(?:{DATE_BODY})$")
_YEAR = re.compile(rf"^{YEAR_BODY}$")
_SLUG = re.compile(SLUG_PATTERN)


def load(path: Path = DEFAULT_PROFILE_PATH) -> Profile:
    """Load and validate the profile at ``path``."""
    try:
        # utf-8-sig for symmetry with the Markdown reader. PyYAML strips a BOM on its own, so
        # this is belt-and-braces here; it is load-bearing in exporter.read_source.
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        msg = f"cannot read {path}: {exc.strerror or exc}"
        raise ProfileError(msg) from exc
    except UnicodeDecodeError as exc:
        msg = f"{path} is not UTF-8 text: re-save it as UTF-8"
        raise ProfileError(msg) from exc
    return loads(text)


class _StrictLoader(yaml.SafeLoader):
    """A safe loader that refuses a duplicated key instead of keeping the last one.

    PyYAML's default silently discards the earlier value, so a copy-paste slip in a long profile
    can delete whole employers and still report success.
    """

    @override
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                msg = f"duplicate key {key!r}"
                raise yaml.constructor.ConstructorError(None, None, msg, key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def loads(text: str) -> Profile:
    """Load and validate a profile from YAML source."""
    try:
        data = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - _StrictLoader extends SafeLoader
    except yaml.YAMLError as exc:
        msg = f"invalid YAML: {exc}"
        raise ProfileError(msg) from exc
    if data is None:
        msg = "the profile is empty"
        raise ProfileError(msg)
    return load_mapping(data)


def load_mapping(data: object) -> Profile:
    """Validate an already-parsed mapping into a :class:`Profile`."""
    profile = _build(Profile, data, "")
    _check_semantics(profile)
    return profile


# --- generic structural validation ----------------------------------------------------------------
def _build[T](cls: type[T], value: object, path: str) -> T:
    """Construct a dataclass from a mapping, validating keys and value types."""
    if not isinstance(value, Mapping):
        msg = f"expected a mapping, got {_kind(value)}"
        raise ProfileError(msg, path or "<root>")

    fields = dataclasses.fields(cls)  # type: ignore[arg-type]
    hints = get_type_hints(cls, include_extras=True)
    known = {info.name for info in fields}
    for key in value:
        if key not in known:
            msg = f"unknown key {key!r}; expected one of {', '.join(sorted(known))}"
            raise ProfileError(msg, _join(path, str(key)))

    kwargs: dict[str, object] = {}
    for info in fields:
        field_path = _join(path, info.name)
        if info.name in value:
            kwargs[info.name] = _coerce(_unwrap(hints[info.name]), value[info.name], field_path)
        elif info.default is dataclasses.MISSING:
            msg = "required key is missing"
            raise ProfileError(msg, field_path)
    return cls(**kwargs)


def _coerce(annotation: object, value: object, path: str) -> object:
    """Validate and convert one value against its declared type."""
    origin = get_origin(annotation)
    if origin is tuple:
        return _coerce_tuple(get_args(annotation)[0], value, path)
    if dataclasses.is_dataclass(annotation) and isinstance(annotation, type):
        return _build(annotation, value, path)
    if annotation is str:
        return _coerce_str(value, path)
    if annotation is int:
        return _coerce_int(value, path)
    if annotation is float:
        return _coerce_float(value, path)
    msg = f"unsupported field type {annotation!r}"  # pragma: no cover - guards model changes
    raise ProfileError(msg, path)  # pragma: no cover


def _coerce_tuple(item_type: object, value: object, path: str) -> tuple[object, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        msg = f"expected a list, got {_kind(value)}"
        raise ProfileError(msg, path)
    return tuple(
        _coerce(_unwrap(item_type), item, f"{path}[{index}]") for index, item in enumerate(value)
    )


def _coerce_str(value: object, path: str) -> str:
    """Accept only real text, exactly as written.

    Strict, so the generated JSON Schema's ``"type": "string"`` tells the truth: YAML turns a
    bare 2018 into an int, hence the hint. Padding is rejected rather than trimmed, because the
    schema's patterns see the raw value — silently normalising ``" 2020-01 "`` would make the
    loader accept a profile that the user's editor flags as invalid against the same schema.
    """
    if not isinstance(value, str):
        quotable = (bool, int, float, datetime.date, datetime.datetime)
        hint = " (quote it)" if isinstance(value, quotable) else ""
        msg = f"expected text, got {_kind(value)}{hint}"
        raise ProfileError(msg, path)
    if value != value.strip():
        msg = "remove the leading or trailing whitespace"
        raise ProfileError(msg, path)
    return value


def _coerce_int(value: object, path: str) -> int:
    # A float with no fractional part is an integer to JSON Schema, so it must be one here too.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"expected a whole number, got {_kind(value)}"
        raise ProfileError(msg, path)
    return value


def _coerce_float(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"expected a number, got {_kind(value)}"
        raise ProfileError(msg, path)
    # NaN slips past every comparison, and neither it nor infinity is valid JSON.
    if not math.isfinite(value):
        msg = f"expected a finite number, got {value}"
        raise ProfileError(msg, path)
    return float(value)


def _unwrap(annotation: object) -> object:
    """Strip ``Annotated[...]`` down to the underlying type."""
    if get_origin(annotation) is Annotated:
        return get_args(annotation)[0]
    return annotation


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _kind(value: object) -> str:
    if value is None:
        return "nothing"
    return type(value).__name__


# --- semantic validation --------------------------------------------------------------------------
def _check_semantics(profile: Profile) -> None:
    """Check the rules that types alone can't express."""
    if profile.schema_version != 1:
        msg = f"unsupported schema_version {profile.schema_version}; this build understands 1"
        raise ProfileError(msg, "schema_version")

    _check_identity(profile)
    if not profile.experience:
        msg = "at least one employer is required"
        raise ProfileError(msg, "experience")

    seen: set[str] = set()
    for index, tenure in enumerate(profile.experience):
        _check_tenure(tenure, f"experience[{index}]", seen)

    for index, education in enumerate(profile.education):
        _require(education.credential, f"education[{index}].credential")
        _require(education.institution, f"education[{index}].institution")
        _check_date(education.completed, f"education[{index}].completed")
    for section in ("certifications", "awards"):
        for index, credential in enumerate(getattr(profile, section)):
            _require(credential.name, f"{section}[{index}].name")
            if credential.year and not _YEAR.match(credential.year):
                msg = f"expected a 4-digit year, got {credential.year!r}"
                raise ProfileError(msg, f"{section}[{index}].year")

    ids = profile.tenure_ids()
    for group_index, group in enumerate(profile.technologies):
        _require(group.group, f"technologies[{group_index}].group")
        for item_index, item in enumerate(group.items):
            _check_technology(item, f"technologies[{group_index}].items[{item_index}]", ids)


def _check_identity(profile: Profile) -> None:
    """Every field the schema marks required must actually carry content."""
    _require(profile.contact.name, "contact.name")
    _require(profile.contact.headline, "contact.headline")
    _require(profile.contact.email, "contact.email")
    for index, link in enumerate(profile.contact.links):
        _require(link.label, f"contact.links[{index}].label")
        _require(link.url, f"contact.links[{index}].url")
    _require(profile.summary, "summary")
    for index, project in enumerate(profile.projects):
        _require(project.name, f"projects[{index}].name")
        _require(project.description, f"projects[{index}].description")


def _check_tenure(tenure: Tenure, path: str, seen: set[str]) -> None:
    if not _SLUG.match(tenure.id):
        msg = f"id must be a lowercase slug like 'acme-corp', got {tenure.id!r}"
        raise ProfileError(msg, f"{path}.id")
    if tenure.id in seen:
        msg = f"duplicate employer id {tenure.id!r}"
        raise ProfileError(msg, f"{path}.id")
    seen.add(tenure.id)
    _require(tenure.company, f"{path}.company")
    if not tenure.roles:
        msg = "at least one role is required"
        raise ProfileError(msg, f"{path}.roles")
    for index, role in enumerate(tenure.roles):
        role_path = f"{path}.roles[{index}]"
        _require(role.title, f"{role_path}.title")
        _check_date(role.start, f"{role_path}.start", required=True)
        _check_date(role.end, f"{role_path}.end", required=True, allow_present=True)
        if role.end != PRESENT and _month(role.end, last=True) < _month(role.start, last=False):
            msg = f"end {role.end!r} is before start {role.start!r}"
            raise ProfileError(msg, f"{role_path}.end")
        for highlight_index, highlight in enumerate(role.highlights):
            _require(highlight.text, f"{role_path}.highlights[{highlight_index}].text")


def _check_technology(item: Technology, path: str, ids: frozenset[str]) -> None:
    _require(item.name, f"{path}.name")
    if item.level and item.level not in LEVELS:
        msg = f"level must be one of {', '.join(LEVELS)}; got {item.level!r}"
        raise ProfileError(msg, f"{path}.level")
    if item.years < 0:
        msg = f"years cannot be negative, got {item.years}"
        raise ProfileError(msg, f"{path}.years")
    for index, employer in enumerate(item.used_at):
        if employer not in ids:
            msg = f"unknown employer id {employer!r}; add it under experience first"
            raise ProfileError(msg, f"{path}.used_at[{index}]")


def _check_date(
    value: str, path: str, *, required: bool = False, allow_present: bool = False
) -> None:
    suffix = " or 'present'" if allow_present else ""
    if not value:
        if required:
            msg = f"a date{suffix or ''} is required"
            raise ProfileError(msg, path)
        return
    if allow_present and value == PRESENT:
        return
    if not _DATE.match(value):
        msg = f"expected YYYY or YYYY-MM{suffix}, got {value!r}"
        raise ProfileError(msg, path)


def _month(value: str, *, last: bool) -> str:
    """Normalise ``YYYY`` to a comparable ``YYYY-MM``, widening to the whole year."""
    if _YEAR.match(value):
        return f"{value}-12" if last else f"{value}-01"
    return value


def _require(value: str, path: str) -> None:
    if not value:
        msg = "must not be empty"
        raise ProfileError(msg, path)
