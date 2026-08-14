"""HTTP surface for :mod:`resume_tailor.service`.

Importing this package pulls in FastAPI but nothing model-facing, and reads no configuration, so
``create_app`` is safe to call on a machine with no API key. See :mod:`resume_tailor.api.app`.

Serve it with::

    uvicorn --factory resume_tailor.api:create_app
"""

from __future__ import annotations

from resume_tailor.api.app import (
    ApplicationResponse,
    ErrorResponse,
    HealthResponse,
    MatchRequest,
    MatchResponse,
    TailorRequest,
    create_app,
)

__all__ = [
    "ApplicationResponse",
    "ErrorResponse",
    "HealthResponse",
    "MatchRequest",
    "MatchResponse",
    "TailorRequest",
    "create_app",
]
