# Resume-Tailor — see README.md
#
#   make setup                 one-time: create .venv and install everything
#   make check                 lint + types + tests (what CI runs)
#   make export APP=<folder>   render applications/<folder> to .docx + .pdf
#
.DEFAULT_GOAL := help

PY      := .venv/bin/python
RUFF    := .venv/bin/ruff
MYPY    := .venv/bin/mypy
PYTEST  := .venv/bin/pytest
PROFILE ?= profile/master-profile.yaml

.PHONY: help setup lint format typecheck test check export example \
        profile-check profile-md profile-schema clean

help:  ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup:  ## Create .venv and install the package plus dev tools (uv if present, else pip)
	@if command -v uv >/dev/null 2>&1; then \
	  uv sync --all-groups; \
	else \
	  echo "uv not found — falling back to python3 -m venv + pip"; \
	  python3 -m venv .venv && .venv/bin/pip install -q -e . pytest pytest-cov ruff mypy types-PyYAML; \
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

example:  ## Render the bundled demo application
	$(PY) -m resume_tailor build applications/example-acme-backend/resume.md
	$(PY) -m resume_tailor build applications/example-acme-backend/cover-letter.md --layout ats

# --- profile --------------------------------------------------------------------------------------
serve:  ## Run the HTTP API on http://127.0.0.1:8000
	$(PY) -m resume_tailor serve

match:
	@test -n "$(APP)" || { echo "usage: make match APP=<folder under applications/>"; exit 1; }
	$(PY) -m resume_tailor match applications/$(APP)/job-description.md

profile-check:  ## Validate the master profile
	$(PY) -m resume_tailor profile validate $(PROFILE)

profile-md:  ## Regenerate the readable Markdown view of the profile
	$(PY) -m resume_tailor profile render $(PROFILE)

profile-schema:  ## Regenerate schema/master-profile.schema.json from the models
	$(PY) -m resume_tailor profile schema

clean:  ## Remove build artefacts and caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage coverage.xml htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
