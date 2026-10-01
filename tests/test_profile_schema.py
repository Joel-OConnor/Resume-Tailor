"""The generated JSON Schema."""

from __future__ import annotations

import dataclasses
import json
import re
from typing import TYPE_CHECKING, Annotated, Any

import pytest

from resume_tailor.errors import ProfileError
from resume_tailor.profile import loader
from resume_tailor.profile import schema as schema_module
from resume_tailor.profile.models import Doc, Link, Profile
from resume_tailor.profile.schema import build_schema
from tests.conftest import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

SCHEMA: dict[str, Any] = build_schema()


def test_it_is_a_2020_12_object_schema() -> None:
    assert SCHEMA["$schema"].endswith("2020-12/schema")
    assert SCHEMA["type"] == "object"
    assert SCHEMA["additionalProperties"] is False


def test_required_keys_match_the_dataclass_fields_without_defaults() -> None:
    assert SCHEMA["required"] == ["contact", "summary", "experience"]


def test_optional_fields_are_present_but_not_required() -> None:
    assert "technologies" in SCHEMA["properties"]
    assert "technologies" not in SCHEMA["required"]


def test_nested_models_become_refs() -> None:
    assert SCHEMA["properties"]["contact"] == {
        "$ref": "#/$defs/Contact",
        "description": "Name, headline, and contact details.",
    }
    assert SCHEMA["$defs"]["Contact"]["properties"]["email"]["type"] == "string"


def test_lists_of_models_become_arrays_of_refs() -> None:
    assert SCHEMA["properties"]["experience"]["type"] == "array"
    assert SCHEMA["properties"]["experience"]["items"] == {"$ref": "#/$defs/Tenure"}


def test_lists_of_scalars_become_arrays_of_scalars() -> None:
    assert SCHEMA["properties"]["notes"]["items"] == {"type": "string"}


def test_every_expected_definition_is_emitted() -> None:
    assert set(SCHEMA["$defs"]) == {
        "Contact",
        "Credential",
        "Education",
        "Highlight",
        "Link",
        "Project",
        "Role",
        "Technology",
        "TechnologyGroup",
        "Tenure",
    }


def test_scalar_types_are_mapped() -> None:
    assert SCHEMA["properties"]["schema_version"]["type"] == "integer"
    assert SCHEMA["$defs"]["Technology"]["properties"]["years"]["type"] == "number"


def test_every_field_carries_its_description() -> None:
    for definition in [SCHEMA, *SCHEMA["$defs"].values()]:
        for name, field in definition["properties"].items():
            assert field.get("description"), f"{name} has no description"


def test_titles_come_from_the_model_docstrings() -> None:
    assert SCHEMA["$defs"]["Tenure"]["title"].startswith("Everything done at one employer")


def test_loader_constraints_are_mirrored_into_the_schema() -> None:
    assert SCHEMA["$defs"]["Technology"]["properties"]["level"]["enum"] == ["", *loader.LEVELS]
    assert SCHEMA["$defs"]["Technology"]["properties"]["years"]["minimum"] == 0
    assert SCHEMA["properties"]["schema_version"]["const"] == 1
    assert "present" in SCHEMA["$defs"]["Role"]["properties"]["end"]["pattern"]


_DATES: tuple[str, ...] = ("2020", "2020-01", "2020-12", "", "present", "2020-00", "2020-13")
_DATES += ("2020-1", "2020-06-15", "20", "20201", "Jan 2020", "२०२०")
_YEARS: tuple[str, ...] = ("2020", "", "20", "20201", "2020-06", "present", "٢٠٢٢")
_SLUGS: tuple[str, ...] = ("acme", "acme-corp", "a1-b2", "", "Acme", "acme_corp", "-acme")
_SLUGS += ("acme-", "acme--corp", "ácme", "acme corp")


def _profile_with(**fields: Any) -> dict[str, Any]:
    """Return a minimal profile: ``start``/``end`` set its role, ``id`` its tenure."""
    role = {"title": "T", "start": "1900", "end": "present"}
    role.update({key: fields.pop(key) for key in ("start", "end") if key in fields})
    tenure = {"id": fields.pop("id", "e"), "company": "E", "roles": [role]}
    return {
        "contact": {"name": "Ada", "headline": "Engineer", "email": "a@b.c"},
        "summary": "s",
        "experience": [tenure],
        **fields,
    }


def _rejected_at(data: dict[str, Any]) -> str | None:
    """Return the path the loader rejects ``data`` at, or ``None`` when it loads."""
    try:
        loader.load_mapping(data)
    except ProfileError as error:
        return error.path
    return None


@pytest.mark.parametrize(
    ("definition", "field", "path", "build", "samples"),
    [
        (
            "Role",
            "start",
            "experience[0].roles[0].start",
            lambda value: _profile_with(start=value),
            _DATES,
        ),
        (
            "Role",
            "end",
            "experience[0].roles[0].end",
            lambda value: _profile_with(end=value),
            _DATES,
        ),
        (
            "Education",
            "completed",
            "education[0].completed",
            lambda value: _profile_with(
                education=[{"credential": "BSc", "institution": "X", "completed": value}]
            ),
            _DATES,
        ),
        (
            "Credential",
            "year",
            "certifications[0].year",
            lambda value: _profile_with(certifications=[{"name": "N", "year": value}]),
            _YEARS,
        ),
        ("Tenure", "id", "experience[0].id", lambda value: _profile_with(id=value), _SLUGS),
    ],
    ids=["Role.start", "Role.end", "Education.completed", "Credential.year", "Tenure.id"],
)
def test_schema_patterns_accept_exactly_what_the_loader_accepts(
    definition: str,
    field: str,
    path: str,
    build: Callable[[str], dict[str, Any]],
    samples: tuple[str, ...],
) -> None:
    """The schema builds its patterns from the loader's; this catches the two ever disagreeing."""
    pattern = SCHEMA["$defs"][definition]["properties"][field]["pattern"]
    disagreements: list[str] = []
    for value in samples:
        rejected_at = _rejected_at(build(value))
        assert rejected_at in {None, path}, f"{value!r} was rejected at {rejected_at}, not {path}"
        if (rejected_at is None) != (re.fullmatch(pattern, value) is not None):
            disagreements.append(value)
    assert not disagreements, f"{definition}.{field}: loader and schema disagree on {disagreements}"


def test_it_is_json_serialisable() -> None:
    assert json.loads(json.dumps(SCHEMA)) == SCHEMA


SCHEMA_FILE = REPO_ROOT / "schema" / "master-profile.schema.json"


def test_the_checked_in_schema_is_up_to_date() -> None:
    """``make profile-schema`` regenerates it; this stops it silently drifting."""
    assert json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) == SCHEMA


def test_the_checked_in_schema_is_byte_for_byte_what_profile_schema_writes(
    tmp_path: Path,
) -> None:
    """``make profile-schema`` must find nothing to change.

    Comparing parsed JSON passed a re-indented, re-ordered or newline-less file that the
    command would rewrite, and a field reordered in the models went unnoticed.
    """
    from resume_tailor import cli

    written = tmp_path / "schema.json"
    assert cli.main(["profile", "schema", "-o", str(written)]) == 0
    assert SCHEMA_FILE.read_bytes() == written.read_bytes()


def test_every_model_field_appears_in_the_schema() -> None:
    assert {field.name for field in dataclasses.fields(Profile)} == set(SCHEMA["properties"])


def test_doc_is_an_immutable_value_object() -> None:
    assert Doc("hello").text == "hello"
    with pytest.raises(dataclasses.FrozenInstanceError):
        Doc("hello").text = "bye"  # type: ignore[misc]


# --- the generic machinery, on synthetic models ---------------------------------------------------
@dataclasses.dataclass(frozen=True, slots=True)
class _AllOptional:
    plain: str = ""
    documented: Annotated[str, Doc("has a description")] = ""


@dataclasses.dataclass(frozen=True, slots=True)
class _Documented:
    """A model with a docstring."""

    value: Annotated[int, Doc("a number")] = 0


def test_a_model_with_no_required_fields_omits_required() -> None:
    assert "required" not in schema_module._describe(_AllOptional, {})


def test_the_auto_generated_dataclass_docstring_is_not_used_as_a_title() -> None:
    """``@dataclass`` synthesises ``Cls(field: type = ...)`` when there is no real docstring."""
    assert _AllOptional.__doc__ is not None
    assert "title" not in schema_module._describe(_AllOptional, {})


def test_a_class_with_no_docstring_at_all_gets_no_title() -> None:
    class Bare:
        pass

    Bare.__doc__ = None
    assert schema_module._title(Bare) == ""


def test_a_field_with_no_doc_gets_no_description() -> None:
    described = schema_module._describe(_AllOptional, {})
    assert "description" not in described["properties"]["plain"]
    assert described["properties"]["documented"]["description"] == "has a description"


def test_a_docstring_becomes_the_title() -> None:
    assert schema_module._describe(_Documented, {})["title"] == "A model with a docstring."


@pytest.mark.parametrize(
    "annotation",
    [str, Annotated[str, "not a Doc marker"], Annotated[str, Doc("")]],
)
def test_doc_returns_empty_when_there_is_no_usable_marker(annotation: object) -> None:
    assert schema_module._doc(annotation) == ""


def test_a_model_is_only_defined_once() -> None:
    definitions: dict[str, Any] = {}
    schema_module._type_schema(Annotated[tuple[Link, ...], Doc("x")], definitions)
    first = definitions["Link"]
    schema_module._type_schema(Annotated[Link, Doc("x")], definitions)
    assert definitions["Link"] is first


def test_the_schema_publishes_the_emptiness_rules_the_loader_enforces() -> None:
    """Without these an editor calls a document valid that `profile validate` rejects."""
    assert SCHEMA["properties"]["summary"]["minLength"] == 1
    assert SCHEMA["properties"]["experience"]["minItems"] == 1
    assert SCHEMA["$defs"]["Tenure"]["properties"]["roles"]["minItems"] == 1
    assert SCHEMA["$defs"]["Contact"]["properties"]["name"]["minLength"] == 1
    assert SCHEMA["$defs"]["Highlight"]["properties"]["text"]["minLength"] == 1


def test_used_at_entries_are_constrained_to_the_slug_shape() -> None:
    items = SCHEMA["$defs"]["Technology"]["properties"]["used_at"]["items"]
    assert items["pattern"] == r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    assert items["pattern"] == SCHEMA["$defs"]["Tenure"]["properties"]["id"]["pattern"]


def test_the_rules_no_keyword_can_express_are_still_written_down() -> None:
    for phrase in ("unique", "must not precede its start", "used_at", "whitespace"):
        assert phrase in SCHEMA["description"]
