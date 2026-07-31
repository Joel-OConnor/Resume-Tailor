"""The generated JSON Schema."""

from __future__ import annotations

import dataclasses
import json
from typing import Annotated, Any

import pytest

from resume_tailor.profile import loader
from resume_tailor.profile import schema as schema_module
from resume_tailor.profile.models import Doc, Link, Profile
from resume_tailor.profile.schema import build_schema
from tests.conftest import REPO_ROOT

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


def test_it_is_json_serialisable() -> None:
    assert json.loads(json.dumps(SCHEMA)) == SCHEMA


def test_the_checked_in_schema_is_up_to_date() -> None:
    """``make profile-schema`` regenerates it; this stops it silently drifting."""
    path = REPO_ROOT / "schema" / "master-profile.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == SCHEMA


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


def test_the_rules_no_keyword_can_express_are_still_written_down() -> None:
    for phrase in ("unique", "must not precede its start", "used_at", "whitespace"):
        assert phrase in SCHEMA["description"]
