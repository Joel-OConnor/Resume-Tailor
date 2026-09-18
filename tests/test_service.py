"""Orchestration: slugs, the application folder, and the atomic-or-nothing guarantee."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from resume_tailor import service
from resume_tailor.agent import TailorResult, Usage
from resume_tailor.errors import DocumentError, FabricationError, ProfileError, RenderError
from resume_tailor.llm import LanguageModel, Reply
from resume_tailor.render import exporter
from resume_tailor.render.pdf import PdfResult
from tests.conftest import LETTER_MD, REPO_ROOT, RESUME_MD, pdf_bytes

if TYPE_CHECKING:
    from collections.abc import Callable

    from resume_tailor.profile import Profile

EXAMPLE_PROFILE = REPO_ROOT / "templates" / "master-profile.example.yaml"

POSTING = """\
Staff Backend Engineer at Acme

We need someone strong in Python and Kubernetes to own our payments platform.
Experience with Terraform and Kafka is required.
"""

FIT_REPORT = "## Fit\n\nStrong match on backend and cloud."
LINKEDIN = "## Headline\n\nStaff Backend Engineer.\n"


def fake_result(**overrides: str) -> TailorResult:
    """Build a generated application that the profile really does support."""
    fields: dict[str, str] = {
        "company": "Acme Corp",
        "role": "Staff Backend Engineer",
        "resume": RESUME_MD,
        "fit_report": FIT_REPORT,
        "cover_letter": LETTER_MD,
        "linkedin": LINKEDIN,
        **overrides,
    }
    return TailorResult(usage=Usage(), **fields)


class FakeModel:
    """A :class:`LanguageModel` that is never actually consulted here."""

    def complete(self, system: str, prompt: str) -> Reply:
        """Return a fixed reply."""
        return Reply(text=f"{system}{prompt}")


def install_agent(monkeypatch: pytest.MonkeyPatch, generate: Callable[..., TailorResult]) -> None:
    """Replace the generation call with a stub.

    Everything above ``agent.tailor`` is deterministic, so the whole service can be exercised
    without a model, a key, or a network — which is also why the API tests can drive it.
    """
    monkeypatch.setattr(service, "tailor", generate)


def draft_of(**overrides: str) -> Callable[..., TailorResult]:
    """Build an agent stub that always returns the same result."""

    def generate(posting: str, profile: Profile, model: LanguageModel) -> TailorResult:
        assert posting
        assert profile.contact.name
        assert isinstance(model, LanguageModel)
        return fake_result(**overrides)

    return generate


def raising(exc: Exception) -> Callable[..., TailorResult]:
    """Build an agent stub that fails the way ``exc`` says."""

    def generate(*_: object, **__: object) -> TailorResult:
        raise exc

    return generate


@pytest.fixture(autouse=True)
def _pdf_always_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep exports off the real headless-Chrome path, which is slow and machine-dependent."""

    def fake(_: str, out: Path) -> PdfResult:
        out.write_bytes(b"%PDF-1.4\n")
        return PdfResult(ok=True)

    monkeypatch.setattr(exporter, "html_to_pdf", fake)


@pytest.fixture
def applications(tmp_path: Path) -> Path:
    return tmp_path / "applications"


def tailor(applications_dir: Path, *, export: bool = False) -> service.Application:
    """Run a tailoring against the bundled example profile."""
    return service.tailor_application(
        POSTING,
        profile_path=EXAMPLE_PROFILE,
        applications_dir=applications_dir,
        model=FakeModel(),
        export=export,
    )


# --- slugify --------------------------------------------------------------------------------------
def test_a_slug_is_the_company_and_role_joined_and_lowercased() -> None:
    assert (
        service.slugify("Acme Corp", "Staff Backend Engineer") == "acme-corp-staff-backend-engineer"
    )


def test_runs_of_punctuation_collapse_to_one_hyphen() -> None:
    assert service.slugify("Acme, Inc.", "Sr. // Engineer") == "acme-inc-sr-engineer"


def test_accents_fold_to_ascii_so_the_folder_name_is_portable() -> None:
    assert service.slugify("Zürich AG", "Señor Engineer") == "zurich-ag-senor-engineer"


def test_a_slug_never_escapes_the_applications_directory() -> None:
    """Path traversal is the one way a company name could steer a write off-target."""
    for company, role in (("../..", "/etc/passwd"), ("..", ".."), ("/", "../secrets")):
        slug = service.slugify(company, role)
        assert "/" not in slug
        assert not slug.startswith(".")
        assert Path("applications", slug).resolve().parent == Path("applications").resolve()


def test_a_slug_is_never_empty() -> None:
    assert service.slugify("", "") == "application"
    assert service.slugify("...", "///") == "application"


def test_a_very_long_name_is_truncated_without_a_trailing_hyphen() -> None:
    slug = service.slugify("a" * 78, "bbbb cccc")
    assert len(slug) <= 80
    assert not slug.endswith("-")


# --- tailor_application ---------------------------------------------------------------------------
def test_tailoring_writes_all_five_documents(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of())
    application = tailor(applications)

    assert application.slug == "acme-corp-staff-backend-engineer"
    assert application.company == "Acme Corp"
    assert application.role == "Staff Backend Engineer"
    assert application.directory == applications / application.slug
    assert [path.name for path in application.files] == [
        "cover-letter.md",
        "fit-report.md",
        "job-description.md",
        "linkedin.md",
        "resume.md",
    ]
    assert (application.directory / "job-description.md").read_text(encoding="utf-8") == POSTING


def test_every_document_ends_in_a_newline(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of(linkedin="no trailing newline"))
    application = tailor(applications)
    for path in application.files:
        assert path.read_text(encoding="utf-8").endswith("\n")


def test_the_fit_report_carries_the_computed_coverage_under_the_models_prose(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of())
    application = tailor(applications)
    report = (application.directory / "fit-report.md").read_text(encoding="utf-8")

    narrative, _, coverage = report.partition("\n---\n")
    assert narrative.strip() == FIT_REPORT
    assert "## Keyword coverage" in coverage
    # Deterministic, not prose: the posting's Kubernetes really is in the example profile.
    assert "Kubernetes" in coverage


def test_exporting_renders_both_resume_layouts_and_a_single_column_letter(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of())
    application = tailor(applications, export=True)

    names = {path.name for path in application.files}
    assert {"resume.docx", "resume.pdf", "resume-polished.docx", "resume-polished.pdf"} <= names
    assert {"cover-letter.docx", "cover-letter.pdf"} <= names
    assert "cover-letter-polished.docx" not in names


def test_tailoring_the_same_job_twice_replaces_the_folder(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of())
    first = tailor(applications)
    (first.directory / "notes-i-left-behind.md").write_text("stale", encoding="utf-8")

    second = tailor(applications)
    assert second.directory == first.directory
    assert "notes-i-left-behind.md" not in {path.name for path in second.files}


def test_a_generation_failure_leaves_no_folder_at_all(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    """The failure this guard exists for: a half-written folder is one a user might send."""
    install_agent(monkeypatch, raising(FabricationError("invented a metric")))

    with pytest.raises(FabricationError):
        tailor(applications)
    # Not even the parent: nothing is created until there is something true to put in it.
    assert not applications.exists()


def test_an_export_failure_leaves_the_previous_version_untouched(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    """A broken re-tailor must not cost the user the resume they already had."""
    install_agent(monkeypatch, draft_of())
    good = tailor(applications, export=False)
    original = (good.directory / "resume.md").read_text(encoding="utf-8")

    install_agent(monkeypatch, draft_of(resume="not a resume at all\n"))
    with pytest.raises(DocumentError):
        tailor(applications, export=True)

    assert (good.directory / "resume.md").read_text(encoding="utf-8") == original
    assert [child.name for child in applications.iterdir()] == [good.slug]


def test_a_write_failure_is_reported_cleanly_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of())

    def refuse(*_: object, **__: object) -> None:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Path, "write_text", refuse)
    with pytest.raises(RenderError, match="Permission denied"):
        tailor(applications)
    assert list(applications.iterdir()) == []


def test_an_unwritable_applications_directory_is_reported_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_agent(monkeypatch, draft_of())
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("in the way", encoding="utf-8")

    with pytest.raises(RenderError, match="cannot write to"):
        tailor(blocked)


def test_a_folder_that_cannot_be_replaced_is_reported_cleanly(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of())
    applications.mkdir(parents=True)
    # A plain file where the folder should go: nothing can be removed or renamed onto it.
    (applications / "acme-corp-staff-backend-engineer").write_text("a file", encoding="utf-8")

    with pytest.raises(RenderError, match="cannot write"):
        tailor(applications)
    assert [child.name for child in applications.iterdir()] == ["acme-corp-staff-backend-engineer"]


def test_a_draft_with_no_company_or_role_still_lands_somewhere(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of(company="", role=""))
    application = tailor(applications)
    assert application.slug == "application"
    assert application.directory.is_dir()


def test_an_invalid_profile_fails_before_the_model_is_asked(
    monkeypatch: pytest.MonkeyPatch, applications: Path, tmp_path: Path
) -> None:
    install_agent(monkeypatch, raising(AssertionError("the agent must not be reached")))
    broken = tmp_path / "broken.yaml"
    broken.write_text("summary: []\n", encoding="utf-8")

    with pytest.raises(ProfileError):
        service.tailor_application(
            POSTING,
            profile_path=broken,
            applications_dir=applications,
            model=FakeModel(),
        )


# --- list_applications ----------------------------------------------------------------------------
def test_listing_a_missing_directory_is_empty_not_an_error(tmp_path: Path) -> None:
    assert service.list_applications(tmp_path / "nothing-here") == ()


def test_listing_returns_folders_in_slug_order_and_skips_stray_files(
    monkeypatch: pytest.MonkeyPatch, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of(company="Zebra"))
    zebra = tailor(applications)
    install_agent(monkeypatch, draft_of(company="Acme"))
    acme = tailor(applications)
    (applications / "README.md").write_text("not an application", encoding="utf-8")
    (applications / ".acme-in-flight").mkdir()

    listed = service.list_applications(applications)
    assert [item.slug for item in listed] == [acme.slug, zebra.slug]
    assert listed[0].company == ""
    assert listed[0].role == ""
    assert [path.name for path in listed[0].files] == [path.name for path in acme.files]


# --- check_profile and match_only -----------------------------------------------------------------
def test_the_profile_summary_counts_what_a_ui_needs_to_show() -> None:
    summary = service.check_profile(EXAMPLE_PROFILE)
    assert summary["name"] == "Jordan Rivera"
    assert summary["employers"] == 2
    assert summary["roles"] == 2
    assert summary["technologies"] == 10
    assert summary["path"] == str(EXAMPLE_PROFILE)


def test_the_profile_summary_surfaces_unconfirmed_notes() -> None:
    """Notes are the claims a resume must not print, so a UI has to be able to see them."""
    notes = service.check_profile(EXAMPLE_PROFILE)["notes"]
    assert isinstance(notes, list)
    assert any("Confirm" in note for note in notes)


def test_the_profile_summary_rejects_an_invalid_profile(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("summary: []\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        service.check_profile(broken)


def test_matching_needs_no_model_and_returns_markdown() -> None:
    markdown = service.match_only(POSTING, EXAMPLE_PROFILE)
    assert markdown.startswith("## Keyword coverage")
    assert "Kubernetes" in markdown


# --- reading profile/raw/ ------------------------------------------------------------------
def test_raw_documents_are_extracted_from_docx_and_text(tmp_path: Path) -> None:
    from docx import Document as new_docx

    from resume_tailor.service import read_raw_documents

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "notes.md").write_text("A brag doc.\n", encoding="utf-8")
    (raw / "resume.txt").write_text("An old resume.\n", encoding="utf-8")
    document = new_docx()
    document.add_paragraph("Lead Software Engineer")
    table = document.add_table(rows=1, cols=1)
    table.rows[0].cells[0].text = "Charter Communications"
    document.save(str(raw / "old.docx"))

    found = read_raw_documents(raw).documents
    assert set(found) == {"notes.md", "old.docx", "resume.txt"}
    assert "Charter Communications" in found["old.docx"], "table cells carry the real content"


def test_unreadable_and_hidden_files_are_reported_not_fatal(tmp_path: Path) -> None:
    """A stray .DS_Store must not stop a build — but a file that yielded nothing is named."""
    from resume_tailor.service import read_raw_documents

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / ".DS_Store").write_bytes(b"\x00\x01")
    (raw / "scan.pdf").write_bytes(b"%PDF-1.4 binary")
    (raw / "broken.docx").write_bytes(b"not really a docx")
    (raw / "portfolio.rtf").write_text("{\\rtf1 An unsupported format.}", encoding="utf-8")
    (raw / "empty.md").write_text("   \n", encoding="utf-8")
    (raw / "good.md").write_text("Real content.\n", encoding="utf-8")
    (raw / "nested").mkdir()

    found = read_raw_documents(raw)
    assert set(found.documents) == {"good.md"}
    # Hidden files and folders are noise; a document the user meant to add is not.
    assert found.skipped == ("broken.docx", "empty.md", "portfolio.rtf", "scan.pdf")


def test_the_projects_own_raw_readme_is_never_career_history(tmp_path: Path) -> None:
    """Feeding the instructions to the model invites the model to write from them."""
    from resume_tailor.service import read_raw_documents

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "README.md").write_text("# Drop your background materials here\n", encoding="utf-8")
    (raw / "notes.md").write_text("Real content.\n", encoding="utf-8")

    found = read_raw_documents(raw)
    assert set(found.documents) == {"notes.md"}
    assert found.skipped == (), "skipping it deliberately is not something to warn about"


def test_a_pdf_resume_is_read(tmp_path: Path) -> None:
    """Most people's only resume is a PDF; silently ignoring it built half a profile."""
    from resume_tailor.service import read_raw_documents

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "resume.pdf").write_bytes(pdf_bytes("Lead Engineer at Charter Communications"))

    found = read_raw_documents(raw)
    assert "Charter Communications" in found.documents["resume.pdf"]
    assert found.skipped == ()


def test_a_scanned_pdf_with_no_text_layer_is_reported(tmp_path: Path) -> None:
    """A scan yields nothing; saying so is the whole point of the skipped list."""
    from resume_tailor.service import read_raw_documents

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "scan.pdf").write_bytes(pdf_bytes(""))

    found = read_raw_documents(raw)
    assert found.documents == {}
    assert found.skipped == ("scan.pdf",)


def test_a_corrupt_pdf_is_reported_not_fatal(tmp_path: Path) -> None:
    from resume_tailor.service import read_raw_documents

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "broken.pdf").write_bytes(b"%PDF-1.4 truncated nonsense")
    assert read_raw_documents(raw).skipped == ("broken.pdf",)


def test_a_missing_raw_directory_is_empty(tmp_path: Path) -> None:
    from resume_tailor.service import read_raw_documents

    found = read_raw_documents(tmp_path / "absent")
    assert (found.documents, found.skipped) == ({}, ())


def test_undecodable_text_is_skipped(tmp_path: Path) -> None:
    from resume_tailor.service import read_raw_documents

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "bad.txt").write_bytes(b"\xff\xfe\x00\x80invalid")
    assert read_raw_documents(raw).documents == {}
