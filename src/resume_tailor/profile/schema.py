"""Derive a JSON Schema from the profile models.

Generated rather than hand-written so it can never drift from :mod:`resume_tailor.profile.models`
— a test asserts the checked-in ``schema/master-profile.schema.json`` matches this output. The
schema is what makes the profile portable: any editor, validator, or model can read the contract
without reading Python.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from resume_tailor.profile.loader import DATE_BODY, LEVELS, PRESENT, SLUG_PATTERN, YEAR_BODY
from resume_tailor.profile.models import Doc, Profile

__all__ = ["SCHEMA_ID", "build_schema"]

SCHEMA_ID = "https://github.com/resume-tailor/schema/master-profile.schema.json"

_PRIMITIVES: dict[object, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}

# Constraints that live in the loader's semantic checks; mirrored here so the schema is useful
# to editors that only speak JSON Schema. The patterns are composed from the loader's own
# pattern bodies, so the schema cannot accept a date, year or id the loader rejects. The empty
# alternatives are the optional fields: the loader skips an empty value there.
_CONSTRAINTS: dict[tuple[str, str], dict[str, Any]] = {
    ("Role", "start"): {"pattern": f"^(?:{DATE_BODY})$"},
    ("Role", "end"): {"pattern": f"^(?:{PRESENT}|{DATE_BODY})$"},
    ("Education", "completed"): {"pattern": f"^(?:|{DATE_BODY})$"},
    ("Credential", "year"): {"pattern": f"^(?:|{YEAR_BODY})$"},
    ("Tenure", "id"): {"pattern": SLUG_PATTERN},
    ("Technology", "level"): {"enum": ["", *LEVELS]},
    ("Technology", "years"): {"minimum": 0},
    ("Profile", "schema_version"): {"const": 1},
    # The loader rejects an empty value for each of these; without minLength an editor
    # validating against this file would call the same document valid.
    ("Contact", "name"): {"minLength": 1},
    ("Contact", "headline"): {"minLength": 1},
    ("Contact", "email"): {"minLength": 1},
    ("Link", "label"): {"minLength": 1},
    ("Link", "url"): {"minLength": 1},
    ("Profile", "summary"): {"minLength": 1},
    ("Profile", "experience"): {"minItems": 1},
    ("Tenure", "company"): {"minLength": 1},
    ("Tenure", "roles"): {"minItems": 1},
    ("Role", "title"): {"minLength": 1},
    ("Highlight", "text"): {"minLength": 1},
    ("TechnologyGroup", "group"): {"minLength": 1},
    ("Technology", "name"): {"minLength": 1},
    ("Technology", "used_at"): {"items": {"pattern": SLUG_PATTERN}},
    ("Education", "credential"): {"minLength": 1},
    ("Education", "institution"): {"minLength": 1},
    ("Credential", "name"): {"minLength": 1},
    ("Project", "name"): {"minLength": 1},
    ("Project", "description"): {"minLength": 1},
}

# Rules no JSON Schema keyword can express; stated in the schema so a reader still learns them.
_CROSS_FIELD_RULES = (
    "Each experience[].id must be unique.",
    "A role's end must not precede its start.",
    "Every technologies[].items[].used_at entry must match an experience[].id in this file.",
    "Text values must not carry leading or trailing whitespace.",
)


def build_schema() -> dict[str, Any]:
    """Return the complete JSON Schema for a master profile."""
    definitions: dict[str, Any] = {}
    root = _describe(Profile, definitions)
    root.pop("title", None)  # the root gets a document title, not the dataclass docstring
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "Master profile",
        "description": (
            "The machine-readable superset of a career. Resume tailoring selects and reframes "
            "from this file; it never adds anything absent from it. Rules this schema cannot "
            "express, enforced by `resume-tailor profile validate`: " + " ".join(_CROSS_FIELD_RULES)
        ),
        **root,
        "$defs": definitions,
    }


def _describe(cls: type, definitions: dict[str, Any]) -> dict[str, Any]:
    """Build the object schema for a dataclass, filling ``definitions`` with nested types."""
    hints = get_type_hints(cls, include_extras=True)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for info in dataclasses.fields(cls):
        annotation = hints[info.name]
        properties[info.name] = {
            **_type_schema(annotation, definitions),
            **_CONSTRAINTS.get((cls.__name__, info.name), {}),
        }
        if description := _doc(annotation):
            properties[info.name]["description"] = description
        if info.default is dataclasses.MISSING:
            required.append(info.name)
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        schema["required"] = required
    if title := _title(cls):
        schema["title"] = title
    return schema


def _title(cls: type) -> str:
    """Return the class docstring's first line, ignoring the one dataclasses auto-generates."""
    docstring = (cls.__doc__ or "").strip()
    if not docstring or docstring.startswith(f"{cls.__name__}("):
        return ""
    return docstring.splitlines()[0]


def _type_schema(annotation: object, definitions: dict[str, Any]) -> dict[str, Any]:
    inner = _unwrap(annotation)
    if get_origin(inner) is tuple:
        return {"type": "array", "items": _type_schema(get_args(inner)[0], definitions)}
    if dataclasses.is_dataclass(inner) and isinstance(inner, type):
        name = inner.__name__
        if name not in definitions:
            definitions[name] = {}  # placeholder guards against recursive models
            definitions[name] = _describe(inner, definitions)
        return {"$ref": f"#/$defs/{name}"}
    if (primitive := _PRIMITIVES.get(inner)) is not None:
        return {"type": primitive}
    msg = f"unsupported field type {inner!r}"  # pragma: no cover - guards model changes
    raise TypeError(msg)  # pragma: no cover


def _unwrap(annotation: object) -> object:
    if get_origin(annotation) is Annotated:
        return get_args(annotation)[0]
    return annotation


def _doc(annotation: object) -> str:
    if get_origin(annotation) is Annotated:
        for extra in get_args(annotation)[1:]:
            if isinstance(extra, Doc):
                return extra.text
    return ""
