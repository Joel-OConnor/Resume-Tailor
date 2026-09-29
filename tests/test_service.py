"""Orchestration: the three runs, the review before every export, the all-or-nothing folder."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor import service
from resume_tailor.agent import (
    COVER_LETTER,
    LINKEDIN,
    RESUME,
    EditResult,
    GeneralResult,
    ProfileEdit,
    TailorResult,
    Usage,
)
from resume_tailor.errors import (
    DocumentError,
    FabricationError,
    ModelError,
    ProfileError,
    RenderError,
)
from resume_tailor.llm import Reply
from resume_tailor.profile import loads
from resume_tailor.render import exporter
from resume_tailor.render.pdf import PdfResult
from resume_tailor.review import Answer, Question
from resume_tailor.service import applications as apps
from resume_tailor.service import profile as profiles
from tests.conftest import LETTER_MD, REPO_ROOT, RESUME_MD, pdf_bytes

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from resume_tailor.profile.models import Profile

EXAMPLE_PROFILE = REPO_ROOT / "templates" / "master-profile.example.yaml"
EXAMPLE_YAML = EXAMPLE_PROFILE.read_text(encoding="utf-8")
BARE_YAML = "\n".join(line for line in EXAMPLE_YAML.splitlines() if not line.startswith("#"))
UPDATED_YAML = BARE_YAML.replace(
    "Mentored 4 engineers; two were promoted within a year.",
    "Mentored 4 engineers; two were promoted within a year, one to staff.",
)

POSTING = """\
Staff Backend Engineer at Acme

We need someone strong in Python and Kubernetes to own our payments platform.
"""

LINKEDIN_MD = "# Jordan Rivera\n\n## Headline\nSenior Backend Engineer"


class FakeModel:
    """A language model the stand-ins below never actually consult."""

    def complete(self, system: str, prompt: str) -> Reply:
        """Return a fixed reply."""
        return Reply(text=f"{system}{prompt}")


class Agent:
    """Stand-ins for every model operation the service calls, recording what they were asked.

    Everything above the agent layer is deterministic, so the whole service can be exercised
    without a model, a key, or a network.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.general = GeneralResult(RESUME_MD, LINKEDIN_MD)
        self.tailored = TailorResult(
            company="Acme Corp",
            role="Staff Backend Engineer",
            fit="A strong match on Python; Kafka is the gap.",
            resume=RESUME_MD,
            cover_letter=LETTER_MD,
            questions=("The posting asks for Kafka. Have you used it?",),
        )
        self.editor_questions: tuple[str, ...] = ("How many engines ran it?",)
        self.revise: Callable[[str], str] = lambda text: text.replace("Babbage", "Charles Babbage")
        self.edits: list[dict[str, Any]] = []
        self.updates: list[tuple[Answer, ...]] = []
        self.updated = UPDATED_YAML
        self.update_error: Exception | None = None
        self.revise_error: Exception | None = None
        self.draft = BARE_YAML
        self.refined = BARE_YAML.replace(
            "Senior backend engineer with 8 years", "Backend engineer, 8 years"
        )
        self.refine_error: Exception | None = None
        monkeypatch.setattr(apps, "write_general", self._write_general)
        monkeypatch.setattr(apps, "tailor", self._tailor)
        monkeypatch.setattr(apps, "edit_documents", self._edit_documents)
        monkeypatch.setattr(profiles, "update_profile", self._update_profile)
        monkeypatch.setattr(profiles, "build_profile", self._build_profile)
        monkeypatch.setattr(profiles, "refine_profile", self._refine_profile)

    def _write_general(
        self, profile: Profile, model: object, *, progress: object = None
    ) -> GeneralResult:
        assert callable(progress)
        assert profile.contact.name
        assert model is not None
        return self.general

    def _tailor(
        self, posting: str, profile: Profile, model: object, *, progress: object = None
    ) -> TailorResult:
        assert callable(progress)
        assert posting == POSTING
        assert profile.contact.name
        assert model is not None
        return self.tailored

    def _edit_documents(  # noqa: PLR0913 - mirrors the real signature
        self,
        documents: Mapping[str, str],
        profile: Profile,
        model: object,
        *,
        flagged: str = "",
        answers: Sequence[Answer] = (),
        progress: object = None,
    ) -> EditResult:
        assert callable(progress)
        assert model is not None
        self.edits.append(
            {
                "documents": dict(documents),
                "flagged": flagged,
                "answers": tuple(answers),
                "profile": profile,
            }
        )
        if not answers:
            return EditResult(dict(documents), self.editor_questions)
        if self.revise_error is not None:
            raise self.revise_error
        return EditResult({kind: self.revise(text) for kind, text in documents.items()})

    def _update_profile(
        self, current: str, answers: Sequence[Answer], model: object, *, progress: object = None
    ) -> ProfileEdit:
        assert current and model is not None and callable(progress)
        self.updates.append(tuple(answers))
        if self.update_error is not None:
            raise self.update_error
        return ProfileEdit(self.updated, loads(self.updated))

    def _build_profile(
        self, documents: Mapping[str, str], model: object, *, progress: object = None
    ) -> tuple[str, Usage]:
        assert documents and model is not None and callable(progress)
        return self.draft, Usage()

    def _refine_profile(
        self, draft: str, documents: Mapping[str, str], model: object, *, progress: object = None
    ) -> ProfileEdit:
        assert draft == self.draft and documents and model is not None and callable(progress)
        if self.refine_error is not None:
            raise self.refine_error
        return ProfileEdit(self.refined, loads(self.refined), ("Tightened the summary.",))


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> Agent:
    return Agent(monkeypatch)


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


@pytest.fixture
def profile_path(tmp_path: Path) -> Path:
    """Copy the example profile somewhere writable, since answering questions rewrites it."""
    path = tmp_path / "profile" / "master-profile.yaml"
    path.parent.mkdir()
    path.write_text(BARE_YAML, encoding="utf-8")
    return path


@pytest.fixture
def answers_log(tmp_path: Path) -> Path:
    return tmp_path / "raw" / "answers.md"


def answering(*replies: str) -> Callable[[tuple[Question, ...]], tuple[Answer, ...]]:
    """Build an asker that answers each question in turn with ``replies``."""

    def ask(questions: tuple[Question, ...]) -> tuple[Answer, ...]:
        return tuple(
            Answer(question, reply) for question, reply in zip(questions, replies, strict=False)
        )

    return ask


def general(applications_dir: Path, profile_path: Path, **options: Any) -> service.Application:
    return service.general_application(
        profile_path=profile_path,
        applications_dir=applications_dir,
        model=FakeModel(),
        **options,
    )


def tailored(applications_dir: Path, profile_path: Path, **options: Any) -> service.Application:
    return service.tailor_application(
        POSTING,
        profile_path=profile_path,
        applications_dir=applications_dir,
        model=FakeModel(),
        **options,
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


# --- the general resume and the LinkedIn profile --------------------------------------------------
@pytest.mark.usefixtures("agent")
def test_the_general_run_writes_the_resume_and_the_linkedin_profile(
    applications: Path, profile_path: Path
) -> None:
    application = general(applications, profile_path, export=False)

    assert application.slug == "general"
    assert application.directory == applications / "general"
    assert [path.name for path in application.files] == ["linkedin.md", "resume.md"]
    assert (application.directory / "linkedin.md").read_text(encoding="utf-8") == LINKEDIN_MD + "\n"
    assert application.company == application.role == application.fit == ""


@pytest.mark.usefixtures("agent")
def test_the_general_run_exports_the_resume_but_not_the_linkedin_text(
    applications: Path, profile_path: Path
) -> None:
    application = general(applications, profile_path)

    assert [path.name for path in application.files] == [
        "linkedin.md",
        "resume.docx",
        "resume.md",
        "resume.pdf",
    ]


def test_the_review_fixes_the_mechanical_problems_and_hands_the_rest_to_the_editor(
    agent: Agent, applications: Path, profile_path: Path
) -> None:
    agent.general = GeneralResult(
        RESUME_MD.replace("Jan 1843 – Present", "Jan 1843 - Present"), LINKEDIN_MD
    )

    application = general(applications, profile_path, export=False)

    written = (application.directory / "resume.md").read_text(encoding="utf-8")
    assert "Jan 1843 – Present" in written
    assert [finding.rule for finding in application.review.applied] == ["dates"]
    edit = agent.edits[0]
    assert "Jan 1843 – Present" in edit["documents"][RESUME], "the editor sees the fixed draft"
    assert edit["documents"][LINKEDIN] == LINKEDIN_MD
    assert "no-outcome" in edit["flagged"], "and what the mechanical read flagged"


def test_without_anyone_to_ask_the_questions_come_back_unasked(
    agent: Agent, applications: Path, profile_path: Path
) -> None:
    application = general(applications, profile_path, export=False)

    assert application.asked is False
    assert application.update is None
    assert Question("How many engines ran it?") in application.questions
    assert len(agent.edits) == 1, "no revision without answers"


def test_a_clean_review_asks_nothing(agent: Agent, applications: Path, profile_path: Path) -> None:
    agent.editor_questions = ()
    clean = RESUME_MD.replace(
        "- Corresponded with Babbage on engine semantics.",
        "- Corresponded with Babbage on engine semantics, fixing 3 of its errors.",
    )
    agent.general = GeneralResult(clean, LINKEDIN_MD)

    def never(_: tuple[Question, ...]) -> tuple[Answer, ...]:
        raise AssertionError

    application = general(applications, profile_path, export=False, ask=never)
    assert application.questions == ()
    assert application.asked is False


def test_answers_go_into_the_profile_and_then_into_the_documents(
    agent: Agent, applications: Path, profile_path: Path, answers_log: Path
) -> None:
    application = general(
        applications,
        profile_path,
        export=False,
        ask=answering("Three engines ran it."),
        answers_path=answers_log,
    )

    assert application.asked is True
    assert application.update is not None
    assert [answer.text for answer in application.update.answers] == ["Three engines ran it."]
    assert "one to staff" in profile_path.read_text(encoding="utf-8")
    assert application.update.backup is not None, "the profile the user had is kept"
    assert application.update.backup.read_text(encoding="utf-8").endswith(BARE_YAML)
    assert application.update.changes == ()
    assert "Three engines ran it." in answers_log.read_text(encoding="utf-8")
    revision = agent.edits[1]
    assert revision["answers"] == application.update.answers
    assert "one to staff" in revision["profile"].experience[0].roles[0].highlights[2].text
    written = (application.directory / "resume.md").read_text(encoding="utf-8")
    assert "Charles Babbage" in written, "the revision is what ships"


def test_answers_that_decline_are_logged_but_change_nothing(
    agent: Agent, applications: Path, profile_path: Path, answers_log: Path
) -> None:
    application = general(
        applications, profile_path, export=False, ask=answering("no"), answers_path=answers_log
    )

    assert application.asked is True
    assert application.update is None
    assert agent.updates == []
    assert profile_path.read_text(encoding="utf-8") == BARE_YAML
    assert "**A:** no" in answers_log.read_text(encoding="utf-8")


@pytest.mark.usefixtures("agent")
def test_skipping_every_question_logs_nothing(
    applications: Path, profile_path: Path, answers_log: Path
) -> None:
    general(applications, profile_path, export=False, ask=answering(""), answers_path=answers_log)
    assert not answers_log.exists()


def test_answers_that_cannot_be_recorded_leave_the_profile_and_the_documents_alone(
    agent: Agent, applications: Path, profile_path: Path, answers_log: Path
) -> None:
    agent.update_error = FabricationError("recorded a figure nobody said")

    application = general(
        applications, profile_path, export=False, ask=answering("Three."), answers_path=answers_log
    )

    assert application.update is not None
    assert application.update.error == "recorded a figure nobody said"
    assert application.problems == (
        "your answers could not be recorded in the profile: recorded a figure nobody said",
    )
    assert profile_path.read_text(encoding="utf-8") == BARE_YAML
    assert len(agent.edits) == 1
    assert "Three." in answers_log.read_text(encoding="utf-8"), "the answer itself is safe"


def test_a_revision_that_fails_still_ships_the_reviewed_documents(
    agent: Agent, applications: Path, profile_path: Path, answers_log: Path
) -> None:
    agent.revise_error = ModelError("the model went away")

    application = general(
        applications, profile_path, export=False, ask=answering("Three."), answers_path=answers_log
    )

    assert application.problems == (
        (
            "your answers are in the profile, but the documents do not use them yet: the model "
            "went away"
        ),
    )
    assert "one to staff" in profile_path.read_text(encoding="utf-8")
    assert "Charles Babbage" not in (application.directory / "resume.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.usefixtures("agent")
def test_regenerating_the_general_folder_replaces_it_whole(
    applications: Path, profile_path: Path
) -> None:
    first = general(applications, profile_path, export=False)
    (first.directory / "stale.txt").write_text("old", encoding="utf-8")

    second = general(applications, profile_path, export=False)

    assert [path.name for path in second.files] == ["linkedin.md", "resume.md"]


def test_an_invalid_profile_fails_before_the_model_is_asked(
    monkeypatch: pytest.MonkeyPatch, applications: Path, tmp_path: Path
) -> None:
    def never(*_: object, **__: object) -> object:
        raise AssertionError

    monkeypatch.setattr(apps, "write_general", never)
    broken = tmp_path / "broken.yaml"
    broken.write_text("summary: []\n", encoding="utf-8")

    with pytest.raises(ProfileError):
        general(applications, broken)
    assert not applications.exists()


# --- a tailored application -----------------------------------------------------------------------
def test_tailoring_writes_the_posting_the_resume_and_the_cover_letter(
    agent: Agent, applications: Path, profile_path: Path
) -> None:
    application = tailored(applications, profile_path, export=False)

    assert application.slug == "acme-corp-staff-backend-engineer"
    assert (application.company, application.role) == ("Acme Corp", "Staff Backend Engineer")
    assert application.fit == "A strong match on Python; Kafka is the gap."
    assert [path.name for path in application.files] == [
        "cover-letter.md",
        "job-description.md",
        "resume.md",
    ]
    assert (application.directory / "job-description.md").read_text(encoding="utf-8") == POSTING
    assert agent.edits[0]["documents"][COVER_LETTER] == LETTER_MD


@pytest.mark.usefixtures("agent")
def test_the_writer_s_questions_are_asked_first(applications: Path, profile_path: Path) -> None:
    application = tailored(applications, profile_path, export=False)

    assert [question.text for question in application.questions[:2]] == [
        "The posting asks for Kafka. Have you used it?",
        "How many engines ran it?",
    ]


@pytest.mark.usefixtures("agent")
def test_exporting_renders_the_resume_and_the_letter_single_column(
    applications: Path, profile_path: Path
) -> None:
    application = tailored(applications, profile_path)

    names = {path.name for path in application.files}
    assert {"resume.docx", "resume.pdf", "cover-letter.docx", "cover-letter.pdf"} <= names
    assert not any("polished" in name for name in names), "the two-column design is opt-in"


@pytest.mark.usefixtures("agent")
def test_every_document_ends_in_a_newline(applications: Path, profile_path: Path) -> None:
    for path in tailored(applications, profile_path, export=False).files:
        assert path.read_text(encoding="utf-8").endswith("\n")


@pytest.mark.usefixtures("agent")
def test_a_generation_failure_leaves_no_folder_at_all(
    monkeypatch: pytest.MonkeyPatch, applications: Path, profile_path: Path
) -> None:
    """The failure this guard exists for: a half-written folder is one a user might send."""

    def invent(*_: object, **__: object) -> TailorResult:
        msg = "invented a metric"
        raise FabricationError(msg)

    monkeypatch.setattr(apps, "tailor", invent)
    with pytest.raises(FabricationError):
        tailored(applications, profile_path)
    assert not applications.exists()


def test_an_export_failure_leaves_the_previous_version_untouched(
    agent: Agent, applications: Path, profile_path: Path
) -> None:
    """A broken re-run must not cost the user the resume they already had."""
    good = tailored(applications, profile_path, export=False)
    original = (good.directory / "resume.md").read_text(encoding="utf-8")

    agent.tailored = TailorResult(
        "Acme Corp", "Staff Backend Engineer", "", "not a resume\n", LETTER_MD
    )
    with pytest.raises(DocumentError):
        tailored(applications, profile_path, export=True)

    assert (good.directory / "resume.md").read_text(encoding="utf-8") == original
    assert [child.name for child in applications.iterdir()] == [good.slug]


@pytest.mark.usefixtures("agent")
def test_a_write_failure_is_reported_cleanly_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, applications: Path, profile_path: Path
) -> None:
    real = Path.write_text

    def refuse(self: Path, *args: Any, **kwargs: Any) -> int:
        if applications in self.parents:
            raise OSError(13, "Permission denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse)
    with pytest.raises(RenderError, match="Permission denied"):
        tailored(applications, profile_path)
    assert list(applications.iterdir()) == []


@pytest.mark.usefixtures("agent")
def test_an_unwritable_applications_directory_is_reported_cleanly(
    tmp_path: Path, profile_path: Path
) -> None:
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("in the way", encoding="utf-8")

    with pytest.raises(RenderError, match="cannot write to"):
        tailored(blocked, profile_path)


@pytest.mark.usefixtures("agent")
def test_a_folder_that_cannot_be_replaced_is_reported_cleanly(
    applications: Path, profile_path: Path
) -> None:
    applications.mkdir(parents=True)
    # A plain file where the folder should go: nothing can be removed or renamed onto it.
    (applications / "acme-corp-staff-backend-engineer").write_text("a file", encoding="utf-8")

    with pytest.raises(RenderError, match="cannot write"):
        tailored(applications, profile_path)
    assert [child.name for child in applications.iterdir()] == ["acme-corp-staff-backend-engineer"]


def test_a_draft_with_no_company_or_role_still_lands_somewhere(
    agent: Agent, applications: Path, profile_path: Path
) -> None:
    agent.tailored = TailorResult("", "", "", RESUME_MD, LETTER_MD)
    application = tailored(applications, profile_path, export=False)
    assert application.slug == "application"


# --- building the profile -------------------------------------------------------------------------
@pytest.fixture
def raw() -> service.RawDocuments:
    return service.RawDocuments({"linkedin.txt": "Jordan Rivera, Senior Backend Engineer"})


def build(raw: service.RawDocuments, out: Path, **options: Any) -> service.ProfileBuild:
    return service.build_master_profile(raw, out=out, model=FakeModel(), **options)


def test_nothing_to_read_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="no readable documents"):
        build(service.RawDocuments({}), tmp_path / "p.yaml")


@pytest.mark.usefixtures("agent")
def test_an_existing_profile_is_never_replaced_without_force(
    raw: service.RawDocuments, profile_path: Path
) -> None:
    with pytest.raises(ProfileError, match="--force"):
        build(raw, profile_path)
    assert profile_path.read_text(encoding="utf-8") == BARE_YAML


@pytest.mark.usefixtures("agent")
def test_the_profile_is_drafted_refined_and_written(
    raw: service.RawDocuments, tmp_path: Path
) -> None:
    out = tmp_path / "profile" / "master-profile.yaml"

    built = build(raw, out)

    written = out.read_text(encoding="utf-8")
    assert written.startswith("# yaml-language-server: $schema=")
    assert "Backend engineer, 8 years" in written
    assert built.path == out
    assert built.backup is None
    assert built.changes == ("Tightened the summary.",)
    assert built.difference == ("summary: rewritten",)
    assert built.refine_error == ""
    assert built.questions == (
        Question(
            "Confirm the exact settlement latency numbers before quoting them in an interview."
        ),
    ), "the profile's open notes come back as questions"
    assert built.update is None


@pytest.mark.usefixtures("agent")
def test_forcing_a_rebuild_keeps_the_profile_it_replaces(
    raw: service.RawDocuments, profile_path: Path
) -> None:
    built = build(raw, profile_path, force=True)

    assert built.backup is not None
    assert built.backup.read_text(encoding="utf-8") == BARE_YAML


def test_a_refinement_that_fails_its_checks_keeps_the_draft(
    agent: Agent, raw: service.RawDocuments, tmp_path: Path
) -> None:
    agent.refine_error = FabricationError("lost the figure '38%'")
    out = tmp_path / "master-profile.yaml"

    built = build(raw, out)

    assert built.refine_error == "lost the figure '38%'"
    assert "Senior backend engineer with 8 years" in out.read_text(encoding="utf-8")
    assert built.changes == built.difference == ()


@pytest.mark.usefixtures("agent")
def test_the_open_questions_are_asked_and_answered_into_the_profile(
    raw: service.RawDocuments, tmp_path: Path, answers_log: Path
) -> None:
    out = tmp_path / "master-profile.yaml"

    built = build(raw, out, ask=answering("It was 38%, measured at p95."), answers_path=answers_log)

    assert built.update is not None
    assert built.update.backup is None, "no backup of a file this same run just wrote"
    assert "one to staff" in out.read_text(encoding="utf-8")
    assert list(tmp_path.glob("*.bak")) == []
    assert "measured at p95" in answers_log.read_text(encoding="utf-8")


@pytest.mark.usefixtures("agent")
def test_declining_every_open_question_leaves_the_refined_profile(
    raw: service.RawDocuments, tmp_path: Path, answers_log: Path
) -> None:
    out = tmp_path / "master-profile.yaml"

    built = build(raw, out, ask=answering("not sure"), answers_path=answers_log)

    assert built.update is None
    assert "Backend engineer, 8 years" in out.read_text(encoding="utf-8")


def test_an_update_that_fails_during_a_build_is_reported_not_raised(
    agent: Agent, raw: service.RawDocuments, tmp_path: Path, answers_log: Path
) -> None:
    agent.update_error = ModelError("rate limited")
    out = tmp_path / "master-profile.yaml"

    built = build(raw, out, ask=answering("Yes."), answers_path=answers_log)

    assert built.update is not None
    assert built.update.error == "rate limited"
    assert "Backend engineer, 8 years" in out.read_text(encoding="utf-8")


def test_a_profile_with_nothing_open_asks_nothing(
    agent: Agent, raw: service.RawDocuments, tmp_path: Path
) -> None:
    agent.refined = "\n".join(
        line for line in agent.refined.splitlines() if "Confirm" not in line and line != "notes:"
    )

    def never(_: tuple[Question, ...]) -> tuple[Answer, ...]:
        raise AssertionError

    built = build(raw, tmp_path / "p.yaml", ask=never)
    assert built.questions == ()


# --- recording answers ----------------------------------------------------------------------------
def test_answers_are_logged_as_a_dated_section(tmp_path: Path) -> None:
    log = tmp_path / "raw" / "answers.md"
    question = Question("What did this achieve?", "Built the thing")

    service.record_answers(log, "applications/general", (Answer(question, "Cut costs 10%."),))
    service.record_answers(log, "applications/general", (Answer(Question("Why?"), "Because."),))

    text = log.read_text(encoding="utf-8")
    assert text.count("· applications/general") == 2
    assert (
        '- **Q:** What did this achieve? (about: "Built the thing")\n  **A:** Cut costs 10%.'
        in text
    )
    assert "- **Q:** Why?\n  **A:** Because." in text


def test_an_unwritable_answers_log_is_reported_cleanly(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("in the way", encoding="utf-8")
    with pytest.raises(RenderError, match="cannot write"):
        service.record_answers(blocked / "answers.md", "x", (Answer(Question("Q?"), "A."),))


@pytest.mark.usefixtures("agent")
def test_nothing_substantive_means_no_update(profile_path: Path, tmp_path: Path) -> None:
    log = tmp_path / "answers.md"
    assert service.apply_answers(profile_path, (), FakeModel(), answers_path=log) is None
    assert not log.exists()


# --- writing the profile --------------------------------------------------------------------------
def test_a_written_profile_points_an_editor_at_the_schema(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "master-profile.yaml"

    assert service.write_profile(out, "summary: s") is None

    first, second = out.read_text(encoding="utf-8").splitlines()
    assert first.startswith("# yaml-language-server: $schema=")
    assert first.endswith("schema/master-profile.schema.json")
    assert (out.parent / first.split("=", 1)[1]).resolve() == (
        REPO_ROOT / "schema" / "master-profile.schema.json"
    ).resolve()
    assert second == "summary: s"


def test_a_profile_that_already_points_at_the_schema_is_left_as_it_is(tmp_path: Path) -> None:
    out = tmp_path / "master-profile.yaml"
    service.write_profile(out, EXAMPLE_YAML)
    assert out.read_text(encoding="utf-8") == EXAMPLE_YAML


def test_without_a_schema_to_point_at_no_comment_is_added(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(profiles, "SCHEMA_PATH", tmp_path / "absent.json")
    out = tmp_path / "master-profile.yaml"
    service.write_profile(out, "summary: s\n")
    assert out.read_text(encoding="utf-8") == "summary: s\n"


def test_a_profile_that_cannot_be_written_is_reported_cleanly(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("in the way", encoding="utf-8")
    with pytest.raises(RenderError, match="cannot write"):
        service.write_profile(blocked / "master-profile.yaml", "summary: s")


def test_a_backup_can_be_skipped(tmp_path: Path) -> None:
    out = tmp_path / "master-profile.yaml"
    out.write_text("old", encoding="utf-8")
    assert service.write_profile(out, "summary: s", back_up=False) is None
    assert list(tmp_path.glob("*.bak")) == []


# --- reading profile/raw/ -------------------------------------------------------------------------
def test_raw_documents_are_extracted_from_docx_and_text(tmp_path: Path) -> None:
    from docx import Document as new_docx

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "notes.md").write_text("A brag doc.\n", encoding="utf-8")
    (raw / "resume.txt").write_text("An old resume.\n", encoding="utf-8")
    document = new_docx()
    document.add_paragraph("Lead Software Engineer")
    table = document.add_table(rows=1, cols=1)
    table.rows[0].cells[0].text = "Charter Communications"
    document.save(str(raw / "old.docx"))

    found = service.read_raw_documents(raw).documents
    assert set(found) == {"notes.md", "old.docx", "resume.txt"}
    assert "Charter Communications" in found["old.docx"], "table cells carry the real content"


def test_unreadable_and_hidden_files_are_reported_not_fatal(tmp_path: Path) -> None:
    """A stray .DS_Store must not stop a build — but a file that yielded nothing is named."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / ".DS_Store").write_bytes(b"\x00\x01")
    (raw / "scan.pdf").write_bytes(b"%PDF-1.4 binary")
    (raw / "broken.docx").write_bytes(b"not really a docx")
    (raw / "portfolio.rtf").write_text("{\\rtf1 An unsupported format.}", encoding="utf-8")
    (raw / "empty.md").write_text("   \n", encoding="utf-8")
    (raw / "good.md").write_text("Real content.\n", encoding="utf-8")
    (raw / "nested").mkdir()

    found = service.read_raw_documents(raw)
    assert set(found.documents) == {"good.md"}
    assert found.skipped == ("broken.docx", "empty.md", "portfolio.rtf", "scan.pdf")


def test_the_projects_own_raw_readme_is_never_career_history(tmp_path: Path) -> None:
    """Feeding the instructions to the model invites the model to write from them."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "README.md").write_text("# Drop your background materials here\n", encoding="utf-8")
    (raw / "notes.md").write_text("Real content.\n", encoding="utf-8")

    found = service.read_raw_documents(raw)
    assert set(found.documents) == {"notes.md"}
    assert found.skipped == ()


def test_a_pdf_resume_is_read(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "resume.pdf").write_bytes(pdf_bytes("Lead Engineer at Charter Communications"))

    found = service.read_raw_documents(raw)
    assert "Charter Communications" in found.documents["resume.pdf"]


def test_a_scanned_pdf_with_no_text_layer_is_reported(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "scan.pdf").write_bytes(pdf_bytes(""))

    found = service.read_raw_documents(raw)
    assert (found.documents, found.skipped) == ({}, ("scan.pdf",))


def test_a_missing_raw_directory_is_empty(tmp_path: Path) -> None:
    found = service.read_raw_documents(tmp_path / "absent")
    assert (found.documents, found.skipped) == ({}, ())


def test_undecodable_text_is_skipped(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "bad.txt").write_bytes(b"\xff\xfe\x00\x80invalid")
    assert service.read_raw_documents(raw).documents == {}


@pytest.mark.usefixtures("agent")
def test_a_long_list_of_open_notes_is_capped_at_the_most_consequential(
    agent: Agent, raw: service.RawDocuments, tmp_path: Path
) -> None:
    """Notes come most consequential first; a build asks the first few, not a questionnaire."""
    notes = "\n".join(f"  - Question {index}?" for index in range(12))
    agent.refined = agent.refined.split("notes:")[0] + f"notes:\n{notes}\n"
    asked: list[tuple[Question, ...]] = []

    def ask(questions: tuple[Question, ...]) -> tuple[Answer, ...]:
        asked.append(questions)
        return ()

    built = build(raw, tmp_path / "p.yaml", ask=ask)

    assert [q.text for q in asked[0]] == [f"Question {index}?" for index in range(8)]
    assert built.questions == asked[0]
    assert len(built.review.questions) == 12, "the rest stay in notes"
