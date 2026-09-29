# Resume-Tailor: see README.md
#
#   make setup                     one-time: create .venv and install everything
#   make profile                   my-documents/career-history/  -> output/master-profile.yaml
#   make resume                    the general resume + the LinkedIn profile -> output/general/
#   make tailor JOB=<posting.md>   a resume + cover letter for that one job  -> output/applications/<company-role>/
#
# JOB can be a path, or just the name of a file in my-documents/job-postings/.
#
# The last two review what they wrote and, at a terminal, ask what only you can answer before
# the final Word and PDF files are written. Everything else here is for working on the tooling.
.DEFAULT_GOAL := help

# The interpreter used to create .venv when uv is not installed. macOS ships an old python3,
# so this is overridable: make setup PYTHON=python3.12
PYTHON  ?= python3
PY      := .venv/bin/python
RUFF    := .venv/bin/ruff
MYPY    := .venv/bin/mypy
PYTEST  := .venv/bin/pytest

.PHONY: help setup profile resume tailor lint format typecheck test check profile-schema clean

help:  ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup:  ## Create .venv and install the package plus dev tools (uv if present, else pip)
	@if command -v uv >/dev/null 2>&1; then \
	  uv sync --all-groups; \
	else \
	  echo "uv not found, falling back to $(PYTHON) -m venv + pip"; \
	  $(PYTHON) -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' || { \
	    echo "error: $(PYTHON) is `$(PYTHON) -V 2>&1`, and this project needs Python 3.12 or newer."; \
	    echo "  Easiest fix: install uv (https://docs.astral.sh/uv/); it fetches the right Python itself."; \
	    echo "  Or point this at your own: make setup PYTHON=python3.12"; \
	    exit 1; \
	  }; \
	  $(PYTHON) -m venv .venv; \
	  .venv/bin/python -m pip install -q --upgrade pip; \
	  .venv/bin/python -m pip install -q -e '.[agent]' pytest pytest-cov ruff mypy types-PyYAML; \
	fi

# --- the three things this project makes ---------------------------------------------------------
profile:  ## Build output/master-profile.yaml from my-documents/career-history/ (FORCE=--force replaces it)
	$(PY) -m resume_tailor profile build $(FORCE)

resume:  ## Write the general resume and the LinkedIn profile into output/general/
	$(PY) -m resume_tailor resume

tailor:  ## Write a resume and cover letter for one job: make tailor JOB=<posting>.md
	@test -n "$(JOB)" || { echo "usage: make tailor JOB=<posting>.md  (a file in my-documents/job-postings/, or any path)"; exit 1; }
	$(PY) -m resume_tailor tailor "$(JOB)"

# --- working on the tooling ----------------------------------------------------------------------
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

profile-schema:  ## Regenerate schema/master-profile.schema.json after changing the profile models
	$(PY) -m resume_tailor profile schema

clean:  ## Remove build artefacts and caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage coverage.xml htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
