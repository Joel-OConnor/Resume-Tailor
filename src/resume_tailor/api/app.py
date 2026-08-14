"""The HTTP adapter: requests in, service calls out, nothing else.

Every decision made here is about transport — validating a body, choosing a status code, keeping
an exception's cause out of the response. All behaviour lives in :mod:`resume_tailor.service`, so
this surface and the CLI cannot drift apart.

Two properties are load-bearing:

* **Building the app never needs an API key.** The model is constructed on the first request that
  actually needs one, which is what keeps ``/health``, ``/profile`` and ``/match`` working on a
  machine that has no key at all — and what lets a key added to ``.env`` take effect without a
  restart.
* **No response body ever carries a stack trace or a credential.** Known failures answer with
  their own one-line message; anything unforeseen answers with a fixed string and nothing else.

Tailoring is synchronous: ``POST /tailor`` holds the connection until the folder is on disk. A
job queue behind the service layer is the natural next step once a UI wants progress.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from resume_tailor import __version__
from resume_tailor.errors import (
    ConfigError,
    DocumentError,
    FabricationError,
    ModelError,
    ProfileError,
    ResumeTailorError,
)
from resume_tailor.llm import build_model, load_settings
from resume_tailor.profile import DEFAULT_PROFILE_PATH
from resume_tailor.service import (
    DEFAULT_APPLICATIONS_DIR,
    Application,
    check_profile,
    list_applications,
    match_only,
    tailor_application,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from starlette.requests import Request

    from resume_tailor.llm import LanguageModel

__all__ = ["create_app"]

UNEXPECTED = "internal error"
"""The entire body of an unforeseen failure. Deliberately says nothing."""

_BAD_REQUEST, _NOT_FOUND, _UNPROCESSABLE = 400, 404, 422
_INTERNAL, _BAD_GATEWAY, _UNAVAILABLE = 500, 502, 503

_STATUS: Final[dict[type[ResumeTailorError], int]] = {
    ConfigError: _UNAVAILABLE,
    ModelError: _BAD_GATEWAY,
    FabricationError: _UNPROCESSABLE,
    ProfileError: _BAD_REQUEST,
    DocumentError: _BAD_REQUEST,
}
"""Known failures and the status each one means. Anything absent is a 500."""


class ErrorResponse(BaseModel):
    """The only shape an error takes: one line, no cause, no traceback."""

    error: str


class HealthResponse(BaseModel):
    """Liveness, plus the build a client is talking to."""

    status: str
    version: str


class MatchRequest(BaseModel):
    """A posting to check against the profile."""

    posting: str = Field(min_length=1, description="The job description, as plain text.")


class MatchResponse(BaseModel):
    """Keyword coverage, ready to paste into a fit report."""

    markdown: str


class TailorRequest(BaseModel):
    """A posting to tailor, and whether to render the Word and PDF files too."""

    posting: str = Field(min_length=1, description="The job description, as plain text.")
    export: bool = Field(default=True, description="Also render .docx and .pdf.")


class ApplicationResponse(BaseModel):
    """One application folder. Paths are strings so the body is plain JSON."""

    slug: str
    company: str
    role: str
    directory: str
    files: list[str]

    @classmethod
    def of(cls, application: Application) -> ApplicationResponse:
        """Convert a service result into its wire form."""
        return cls(
            slug=application.slug,
            company=application.company,
            role=application.role,
            directory=str(application.directory),
            files=[str(path) for path in application.files],
        )


def default_model() -> LanguageModel:
    """Build the configured Anthropic-backed model.

    Called per request rather than at startup, so a machine with no key still serves everything
    that does not need one.
    """
    return build_model(load_settings())


async def _known_failure(_request: Request, exc: ResumeTailorError) -> JSONResponse:
    """Answer a known failure with its own message and the status that failure means.

    These messages are written for the user — the profile path that failed validation, the
    keyword that could not be evidenced — so passing them straight through is the point.
    """
    return JSONResponse(
        status_code=_STATUS.get(type(exc), _INTERNAL),
        content=ErrorResponse(error=str(exc)).model_dump(),
    )


async def _http_failure(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Reshape Starlette's ``detail`` into this API's single error shape."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=str(exc.detail)).model_dump(),
    )


async def _unforeseen_failure(_request: Request, _exc: Exception) -> JSONResponse:
    """Answer anything unforeseen with a fixed line.

    The exception is dropped rather than described: an unexpected error is exactly where a
    credential surfaces — an SDK repr, a URL carrying a token, a path holding a key file — and no
    client needs any of it in order to know the request failed.
    """
    return JSONResponse(status_code=_INTERNAL, content=ErrorResponse(error=UNEXPECTED).model_dump())


def create_app(
    *,
    model_factory: Callable[[], LanguageModel] | None = None,
    profile_path: Path | None = None,
    applications_dir: Path | None = None,
) -> FastAPI:
    """Build the application, with every dependency injectable.

    A test passes a fake ``model_factory`` and temporary paths, and so never touches a real model
    or a real key. Left unset, each argument resolves to the same default the CLI uses.
    """
    make_model = model_factory or default_model
    profile = profile_path or DEFAULT_PROFILE_PATH
    applications = applications_dir or DEFAULT_APPLICATIONS_DIR

    app = FastAPI(
        title="Resume-Tailor",
        version=__version__,
        summary="Tailor a resume to one job description from a structured career profile.",
    )
    # Starlette types every handler as taking a bare `Exception`, so a handler that names the
    # class it was registered for — which is the only reason to register it — cannot type-check.
    # Narrowing inside each handler instead would add a branch that can never be taken.
    app.add_exception_handler(ResumeTailorError, _known_failure)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_failure)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unforeseen_failure)

    # Handlers are plain `def`, not `async def`: loading a profile, matching a posting and
    # calling a model all block, and FastAPI runs a sync handler in a worker thread rather than
    # stalling the event loop for every other request.
    @app.get("/health", response_model=HealthResponse, summary="Liveness and version")
    def health() -> HealthResponse:
        """Report that the service is up. Needs no profile and no API key."""
        return HealthResponse(status="ok", version=__version__)

    @app.get("/profile", response_model=None, summary="What the master profile contains")
    def profile_summary() -> dict[str, object]:
        """Summarise the profile, including everything it still lists as unconfirmed."""
        return check_profile(profile)

    @app.post("/match", response_model=MatchResponse, summary="Keyword coverage for a posting")
    def match(request: MatchRequest) -> MatchResponse:
        """Score a posting against the profile. Deterministic — no model, no API key."""
        return MatchResponse(markdown=match_only(request.posting, profile))

    @app.post("/tailor", response_model=ApplicationResponse, summary="Tailor an application")
    def tailor(request: TailorRequest) -> ApplicationResponse:
        """Generate a complete application folder. This is the call that needs a key."""
        return ApplicationResponse.of(
            tailor_application(
                request.posting,
                profile_path=profile,
                applications_dir=applications,
                model=make_model(),
                export=request.export,
            )
        )

    @app.get("/applications", response_model=list[ApplicationResponse], summary="Every application")
    def applications_index() -> list[ApplicationResponse]:
        """List the application folders already on disk."""
        return [ApplicationResponse.of(item) for item in list_applications(applications)]

    @app.get("/applications/{slug}", response_model=ApplicationResponse, summary="One application")
    def application_detail(slug: str) -> ApplicationResponse:
        """Return one application folder by slug."""
        for item in list_applications(applications):
            if item.slug == slug:
                return ApplicationResponse.of(item)
        msg = f"no application named {slug!r}"
        raise HTTPException(status_code=_NOT_FOUND, detail=msg)

    return app
