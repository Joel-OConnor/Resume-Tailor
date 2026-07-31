"""Markdown → block model."""

from __future__ import annotations

import pytest

from resume_tailor.documents import parse
from resume_tailor.documents.blocks import (
    Bullet,
    Document,
    Entry,
    HeaderLine,
    Meta,
    Name,
    Paragraph,
    Section,
    SectionGroup,
    SkillLine,
    Span,
)
from resume_tailor.errors import DocumentError
from tests.conftest import RESUME_MD


def test_missing_name_is_an_error() -> None:
    with pytest.raises(DocumentError, match="no '# Name' line"):
        parse("## Summary\nnothing above me")


def test_name_and_header_lines() -> None:
    document = parse("# Ada\nPrincipal Engineer\nada@example.com | London\n\n## Summary\nhi")
    assert document.blocks[0] == Name((Span("Ada"),))
    assert document.blocks[1] == HeaderLine((Span("Principal Engineer"),))
    assert document.blocks[2] == HeaderLine((Span("ada@example.com | London"),))


def test_content_before_the_name_is_an_error_not_a_silent_drop() -> None:
    """It would vanish from a document the user is about to submit."""
    with pytest.raises(DocumentError, match="content above the '# Name' line"):
        parse("Draft v3 — do not send\n\n# Ada\n\n## Summary\nhi")


def test_blank_lines_before_the_name_are_fine() -> None:
    assert parse("\n  \n# Ada\n\n## Summary\nhi").name == "Ada"


def test_comments_are_stripped() -> None:
    document = parse("<!--\n# Fake Name\nnotes\n-->\n# Ada\n\n## Summary\nhi")
    assert document.name == "Ada"


def test_header_stops_at_a_section() -> None:
    document = parse("# Ada\n## Summary\nhi")
    assert not [block for block in document.blocks if isinstance(block, HeaderLine)]


def test_sections_entries_and_meta() -> None:
    document = parse("# Ada\n\n## Experience\n### Acme — Engineer\nRemote | 2020 – 2021\nprose")
    assert document.blocks[1:] == (
        Section("Experience"),
        Entry((Span("Acme — Engineer"),)),
        Meta((Span("Remote | 2020 – 2021", italic=True),)),
        Paragraph((Span("prose"),)),
    )


def test_only_the_first_line_after_an_entry_is_meta() -> None:
    document = parse("# Ada\n\n## Experience\n### Acme\n2020\n2021\n2022")
    metas = [block for block in document.blocks if isinstance(block, Meta)]
    paragraphs = [block for block in document.blocks if isinstance(block, Paragraph)]
    assert metas == [Meta((Span("2020", italic=True),))]
    assert paragraphs == [Paragraph((Span("2021 2022"),))]


def test_a_blank_line_cancels_the_pending_meta() -> None:
    document = parse("# Ada\n\n## Experience\n### Acme\n\n2020")
    assert not [block for block in document.blocks if isinstance(block, Meta)]


def test_a_bullet_directly_after_an_entry_cancels_the_pending_meta() -> None:
    document = parse("# Ada\n\n## Experience\n### Acme\n- did a thing")
    assert not [block for block in document.blocks if isinstance(block, Meta)]


@pytest.mark.parametrize("marker", ["-", "*"])
def test_both_bullet_markers(marker: str) -> None:
    document = parse(f"# Ada\n\n## Skills\n{marker} one")
    assert document.blocks[-1] == Bullet((Span("one"),))


def test_bullet_with_a_bold_lead_in() -> None:
    document = parse("# Ada\n\n## Experience\n- **Scope:** owned it")
    assert document.blocks[-1] == Bullet((Span("Scope:", bold=True), Span(" owned it")))


def test_skill_line() -> None:
    document = parse("# Ada\n\n## Skills\n**Languages:** Python, Go")
    assert document.blocks[-1] == SkillLine("Languages", (Span("Python, Go"),))


def test_skill_line_with_no_items() -> None:
    document = parse("# Ada\n\n## Skills\n**Languages:**")
    assert document.blocks[-1] == SkillLine("Languages", ())


def test_any_line_opening_with_a_bold_label_is_a_skill_line() -> None:
    document = parse("# Ada\n\n## Summary\n**Note:** this has **two** bold runs")
    assert isinstance(document.blocks[-1], SkillLine)


def test_bold_later_in_a_line_leaves_it_a_paragraph() -> None:
    document = parse("# Ada\n\n## Summary\nplain **bold** tail")
    assert isinstance(document.blocks[-1], Paragraph)


@pytest.mark.parametrize("rule", ["---", "----", "___", "***"])
def test_horizontal_rules_are_dropped(rule: str) -> None:
    document = parse(f"# Ada\n\n## Summary\nbefore\n{rule}\nafter")
    assert [block for block in document.blocks if isinstance(block, Paragraph)] == [
        Paragraph((Span("before"),)),
        Paragraph((Span("after"),)),
    ]


def test_consecutive_prose_lines_join_into_one_paragraph() -> None:
    document = parse("# Ada\n\n## Summary\nline one\nline two\n\nline three")
    assert [block for block in document.blocks if isinstance(block, Paragraph)] == [
        Paragraph((Span("line one line two"),)),
        Paragraph((Span("line three"),)),
    ]


def test_a_trailing_paragraph_is_flushed() -> None:
    assert parse("# Ada\n\n## Summary\nlast line").blocks[-1] == Paragraph((Span("last line"),))


def test_name_of_an_empty_document_is_blank() -> None:
    assert Document().name == ""


def test_groups_slice_the_document_by_section() -> None:
    groups = parse(RESUME_MD).groups()
    assert [group.title for group in groups] == [
        "",
        "Summary",
        "Skills",
        "Experience",
        "Education",
        "Certifications",
    ]
    assert len(groups[0].blocks) == 3  # name + two header lines


def test_group_key_is_casefolded() -> None:
    assert SectionGroup("  Technical Core ", ()).key == "technical core"


def test_a_document_with_no_sections_is_one_group() -> None:
    assert [group.title for group in parse("# Ada\ncontact").groups()] == [""]


def test_name_is_found_even_when_it_is_not_the_first_block() -> None:
    document = Document((HeaderLine((Span("stray"),)), Name((Span("Ada"),))))
    assert document.name == "Ada"


def test_a_trailing_backslash_is_a_hard_line_break() -> None:
    """Without this the shipped cover letter signs off as one run-on line."""
    document = parse("# Ada\n\n## X\nSincerely,\\\nAda Lovelace")
    assert [b for b in document.blocks if isinstance(b, Paragraph)] == [
        Paragraph((Span("Sincerely,"),)),
        Paragraph((Span("Ada Lovelace"),)),
    ]


def test_a_hard_break_ends_the_paragraph_it_is_in() -> None:
    document = parse("# Ada\n\n## X\nwrapped line one\nline two\\\nafter the break")
    assert [b for b in document.blocks if isinstance(b, Paragraph)] == [
        Paragraph((Span("wrapped line one line two"),)),
        Paragraph((Span("after the break"),)),
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("- a bullet\\", Bullet((Span("a bullet"),))),
        ("**Label:** items\\", SkillLine("Label", (Span("items"),))),
    ],
)
def test_a_stray_hard_break_never_survives_into_a_block(source: str, expected: object) -> None:
    """The marker used to be stripped on prose lines only, so it printed on every other kind."""
    assert parse(f"# Ada\n\n## X\n{source}").blocks[-1] == expected


def test_a_stray_hard_break_never_survives_onto_a_meta_line() -> None:
    document = parse("# Ada\n\n## X\n### Acme\n2020 – 2024\\")
    assert document.blocks[-1] == Meta((Span("2020 – 2024", italic=True),))


def test_an_escaped_backslash_at_end_of_line_is_not_a_break() -> None:
    document = parse("# Ada\n\n## X\nends in a literal backslash\\\\\nsame paragraph")
    assert [b for b in document.blocks if isinstance(b, Paragraph)] == [
        Paragraph((Span("ends in a literal backslash\\ same paragraph"),))
    ]


def test_a_hard_break_marker_never_survives_on_the_name_or_header_lines() -> None:
    """The most-read lines on the page; a stray backslash there is unmissable."""
    document = parse("# Ada Lovelace\\\nada@example.com | London\\\n\n## Summary\nhi")
    assert document.name == "Ada Lovelace"
    assert document.blocks[1] == HeaderLine((Span("ada@example.com | London"),))


def test_a_line_holding_only_the_marker_keeps_the_pending_meta_slot() -> None:
    document = parse("# Ada\n\n## Experience\n### Acme\n\\\nAustin | 2021")
    assert document.blocks[-1] == Meta((Span("Austin | 2021", italic=True),))


def test_control_characters_from_a_word_paste_are_stripped() -> None:
    r"""python-docx passes run text through untouched; a \x0b would crash the export."""
    document = parse("# Ada\n\n## Summary\nPasted\x0bfrom Word\x07here.")
    assert document.blocks[-1] == Paragraph((Span("Pastedfrom Wordhere."),))


def test_a_tab_becomes_spaces_rather_than_vanishing() -> None:
    assert parse("# Ada\n\n## Summary\na\tb").blocks[-1] == Paragraph((Span("a   b"),))
