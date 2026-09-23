# Resume-Tailor — see README.md
#
#   make setup                 one-time: create .venv and install everything
#   make profile               draft profile/master-profile.yaml from profile/raw/
#   make resume                render the whole profile as an untailored resume (no API key)
#   make tailor                tailor every posting in jobs/ into applications/
#   make check                 lint + types + tests (what CI runs)
#   make export APP=<folder>   render applications/<folder> to .docx + .pdf
#   make review APP=<folder>   fix the easy things in a resume, then ask about the rest
#
.DEFAULT_GOAL := help

# The interpreter used to create .venv when uv is not installed. macOS ships an old python3,
# so this is overridable: make setup PYTHON=python3.12
PYTHON  ?= python3
PY      := .venv/bin/python
RUFF    := .venv/bin/ruff
MYPY    := .venv/bin/mypy
PYTEST  := .venv/bin/pytest
PROFILE ?= profile/master-profile.yaml

.PHONY: help setup lint format typecheck test check export example serve match tailor resume \
        review profile profile-check profile-md profile-schema clean

help:  ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup:  ## Create .venv and install the package plus dev tools (uv if present, else pip)
	@if command -v uv >/dev/null 2>&1; then \
	  uv sync --all-groups; \
	else \
	  echo "uv not found — falling back to $(PYTHON) -m venv + pip"; \
	  $(PYTHON) -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' || { \
	    echo "error: $(PYTHON) is `$(PYTHON) -V 2>&1`, and this project needs Python 3.12 or newer."; \
	    echo "  Easiest fix: install uv (https://docs.astral.sh/uv/) — it fetches the right Python itself."; \
	    echo "  Or point this at your own: make setup PYTHON=python3.12"; \
	    exit 1; \
	  }; \
	  $(PYTHON) -m venv .venv; \
	  .venv/bin/python -m pip install -q --upgrade pip; \
	  .venv/bin/python -m pip install -q -e '.[agent]' pytest pytest-cov ruff mypy types-PyYAML httpx; \
	fi

# --- quality gates --------------------------------------------------------------------------------
lint:  ## Lint and check formatting
	$(RUFF) check .
	$(RUFF) format --check .

format:  ## Auto-fix lint findings and reformat
	$(RUFF) check . --fix
	$(RUFF) format .

typecheck:  ## Run mypy in strict mode
	$(MYPY)

test:  ## Run the test suite (100% coverage required)
	$(PYTEST)

check: lint typecheck test  ## Everything CI runs

# --- documents ------------------------------------------------------------------------------------
export:  ## Render applications/$(APP)/*.md to .docx + .pdf
	@test -n "$(APP)" || { echo "usage: make export APP=<folder under applications/>"; exit 1; }
	$(PY) -m resume_tailor build applications/$(APP)/resume.md
	@if [ -f applications/$(APP)/cover-letter.md ]; then \
	  $(PY) -m resume_tailor build applications/$(APP)/cover-letter.md --layout ats; \
	fi

review:  ## Review applications/$(APP)/resume.md: fix the easy things, re-export, then ask about the rest
	@test -n "$(APP)" || { echo "usage: make review APP=<folder under applications/>"; exit 1; }
	$(PY) -m resume_tailor review applications/$(APP)/resume.md --export

example:  ## Render the bundled demo application
	$(PY) -m resume_tailor build applications/example-acme-backend/resume.md
	$(PY) -m resume_tailor build applications/example-acme-backend/cover-letter.md --layout ats

# --- profile --------------------------------------------------------------------------------------
serve:  ## Run the HTTP API on http://127.0.0.1:8000
	$(PY) -m resume_tailor serve

match:  ## Score applications/$(APP)/job-description.md against the profile (no API key)
	@test -n "$(APP)" || { echo "usage: make match APP=<folder under applications/>"; exit 1; }
	$(PY) -m resume_tailor match applications/$(APP)/job-description.md

tailor:  ## Tailor every posting in jobs/ (or JOB=<file>) into applications/
	$(PY) -m resume_tailor tailor $(JOB)

resume:  ## Render the whole profile as an untailored resume in applications/general/ (RESUME_ARGS=...)
	$(PY) -m resume_tailor general $(RESUME_ARGS)

profile:  ## Draft the master profile from profile/raw/ (add FORCE=--force to replace one)
	$(PY) -m resume_tailor profile build $(FORCE)

profile-check:  ## Validate the master profile
	$(PY) -m resume_tailor profile validate $(PROFILE)

profile-md:  ## Regenerate the readable Markdown view of the profile
	$(PY) -m resume_tailor profile render $(PROFILE)

profile-schema:  ## Regenerate schema/master-profile.schema.json from the models
	$(PY) -m resume_tailor profile schema

clean:  ## Remove build artefacts and caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage coverage.xml htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
