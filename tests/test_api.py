"""The HTTP surface: status codes, response shapes, and what leaks (nothing)."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import pytest
from starlette.exceptions import StarletteDeprecationWarning

from resume_tailor import __version__
from resume_tailor.api import create_app
from resume_tailor.api.app import UNEXPECTED
from resume_tailor.errors import ConfigError, FabricationError, ModelError, RenderError
from resume_tailor.render import exporter
from resume_tailor.render.pdf import PdfResult
from tests.test_service import EXAMPLE_PROFILE, POSTING, FakeModel, draft_of, install_agent, raising

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fastapi import FastAPI

    from resume_tailor.llm import LanguageModel

# Starlette 1.6 prefers `httpx2` and warns when it finds `httpx` instead. The suite turns warnings
# into errors, and this one fires while `fastapi.testclient` is being imported — before any marker
# or fixture could suppress it. Adding `httpx2` to the dev dependency group removes the need for
# this, at which point the filter matches nothing and can go.
warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)

from fastapi.testclient import TestClient  # noqa: E402

SENSITIVE = "sk-ant-api03-do-not-leak-this"


@pytest.fixture(autouse=True)
def _pdf_always_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep exports off the real headless-Chrome path, which is slow and machine-dependent."""

    def fake(_: str, out: Path) -> PdfResult:
        out.write_bytes(b"%PDF-1.4\n")
        return PdfResult(ok=True)

    monkeypatch.setattr(exporter, "html_to_pdf", fake)


@pytest.fixture(autouse=True)
def _no_api_key_anywhere(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run every test as if the machine has never been configured.

    Both halves matter: the environment variable and the ``.env`` the loader reads from the
    working directory. Without this, whether ``/health`` really works without a key would depend
    on whose laptop the suite ran on.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def applications(tmp_path: Path) -> Path:
    return tmp_path / "applications"


def app_for(
    applications_dir: Path,
    profile: Path = EXAMPLE_PROFILE,
    model_factory: Callable[[], LanguageModel] | None = None,
) -> FastAPI:
    """Build an app wired to temporary paths and a model that is never really consulted."""
    return create_app(
        model_factory=model_factory or FakeModel,
        profile_path=profile,
        applications_dir=applications_dir,
    )


@pytest.fixture
def client(applications: Path) -> TestClient:
    return TestClient(app_for(applications))


# --- what works with no key at all ----------------------------------------------------------------
def test_the_app_can_be_built_with_no_key_and_no_configuration() -> None:
    """Reading settings at construction time would make /health need a key to answer."""
    assert create_app() is not None


def test_health_reports_the_version(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_health_and_match_answer_without_an_api_key(applications: Path) -> None:
    """The deterministic half of the product must work on an unconfigured machine."""
    client = TestClient(create_app(profile_path=EXAMPLE_PROFILE, applications_dir=applications))

    assert client.get("/health").status_code == 200
    match = client.post("/match", json={"posting": POSTING})
    assert match.status_code == 200
    assert "## Keyword coverage" in match.json()["markdown"]


def test_tailoring_without_a_key_is_unavailable_not_a_crash(applications: Path) -> None:
    client = TestClient(create_app(profile_path=EXAMPLE_PROFILE, applications_dir=applications))
    response = client.post("/tailor", json={"posting": POSTING})

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["error"]


# --- /profile -------------------------------------------------------------------------------------
def test_the_profile_summary_includes_counts_and_unconfirmed_notes(client: TestClient) -> None:
    body = client.get("/profile").json()
    assert body["name"] == "Jordan Rivera"
    assert body["employers"] == 2
    assert any("Confirm" in note for note in body["notes"])


def test_an_invalid_profile_is_a_bad_request(applications: Path, tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("summary: []\n", encoding="utf-8")
    client = TestClient(app_for(applications, broken))

    response = client.get("/profile")
    assert response.status_code == 400
    assert response.json()["error"] == "contact: required key is missing"


# --- /match ---------------------------------------------------------------------------------------
def test_matching_returns_markdown(client: TestClient) -> None:
    response = client.post("/match", json={"posting": POSTING})
    assert response.status_code == 200
    assert "Kubernetes" in response.json()["markdown"]


def test_an_empty_posting_is_rejected_before_any_work_happens(client: TestClient) -> None:
    assert client.post("/match", json={"posting": ""}).status_code == 422


# --- /tailor --------------------------------------------------------------------------------------
def test_tailoring_returns_the_application_it_wrote(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, applications: Path
) -> None:
    install_agent(monkeypatch, draft_of())
    response = client.post("/tailor", json={"posting": POSTING, "export": False})

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "acme-corp-staff-backend-engineer"
    assert body["company"] == "Acme Corp"
    assert body["role"] == "Staff Backend Engineer"
    assert body["directory"] == str(applications / body["slug"])
    assert sorted(name.rsplit("/", 1)[-1] for name in body["files"]) == [
        "cover-letter.md",
        "fit-report.md",
        "job-description.md",
        "linkedin.md",
        "resume.md",
    ]


def test_tailoring_exports_by_default(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    install_agent(monkeypatch, draft_of())
    body = client.post("/tailor", json={"posting": POSTING}).json()
    assert any(name.endswith("resume.docx") for name in body["files"])
    assert any(name.endswith("resume-polished.pdf") for name in body["files"])


# --- error mapping --------------------------------------------------------------------------------
def test_a_fabricated_claim_is_unprocessable(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    install_agent(monkeypatch, raising(FabricationError("invented a metric")))
    response = client.post("/tailor", json={"posting": POSTING})

    assert response.status_code == 422
    assert response.json() == {"error": "invented a metric"}


def test_an_unreachable_model_is_a_bad_gateway(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    install_agent(monkeypatch, raising(ModelError("rate limited by the API")))
    response = client.post("/tailor", json={"posting": POSTING})

    assert response.status_code == 502
    assert response.json() == {"error": "rate limited by the API"}


def test_a_missing_configuration_is_unavailable(applications: Path) -> None:
    def refuse() -> LanguageModel:
        msg = "no ANTHROPIC_API_KEY found"
        raise ConfigError(msg)

    client = TestClient(app_for(applications, model_factory=refuse))
    response = client.post("/tailor", json={"posting": POSTING})

    assert response.status_code == 503
    assert response.json() == {"error": "no ANTHROPIC_API_KEY found"}


def test_a_draft_that_breaks_the_format_contract_is_a_bad_request(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    install_agent(monkeypatch, draft_of(resume="not a resume at all\n"))
    response = client.post("/tailor", json={"posting": POSTING})

    assert response.status_code == 400
    assert response.json()["error"]


def test_an_unmapped_failure_is_a_server_error_carrying_its_own_message(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    install_agent(monkeypatch, raising(RenderError("cannot write /nope/resume.docx")))
    response = client.post("/tailor", json={"posting": POSTING})

    assert response.status_code == 500
    assert response.json() == {"error": "cannot write /nope/resume.docx"}


def test_an_unforeseen_failure_never_reaches_the_client(applications: Path) -> None:
    """The one path where a credential could surface, so the body says nothing at all."""

    def explode() -> LanguageModel:
        msg = f"connection to https://api.example/v1?key={SENSITIVE} failed"
        raise RuntimeError(msg)

    app = app_for(applications, model_factory=explode)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/tailor", json={"posting": POSTING})

    assert response.status_code == 500
    assert response.json() == {"error": UNEXPECTED}
    assert SENSITIVE not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text


# --- /applications --------------------------------------------------------------------------------
def test_listing_is_empty_before_anything_is_tailored(client: TestClient) -> None:
    assert client.get("/applications").json() == []


def test_listing_reports_every_folder_on_disk(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    install_agent(monkeypatch, draft_of(company="Zebra"))
    client.post("/tailor", json={"posting": POSTING, "export": False})
    install_agent(monkeypatch, draft_of(company="Acme"))
    client.post("/tailor", json={"posting": POSTING, "export": False})

    listed = client.get("/applications").json()
    assert [item["slug"] for item in listed] == [
        "acme-staff-backend-engineer",
        "zebra-staff-backend-engineer",
    ]


def test_one_application_can_be_fetched_by_slug(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    install_agent(monkeypatch, draft_of())
    slug = client.post("/tailor", json={"posting": POSTING, "export": False}).json()["slug"]

    response = client.get(f"/applications/{slug}")
    assert response.status_code == 200
    assert response.json()["slug"] == slug


def test_an_unknown_slug_is_a_not_found_in_the_same_error_shape(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    install_agent(monkeypatch, draft_of())
    client.post("/tailor", json={"posting": POSTING, "export": False})

    response = client.get("/applications/never-applied-here")
    assert response.status_code == 404
    assert response.json() == {"error": "no application named 'never-applied-here'"}
