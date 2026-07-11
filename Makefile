# Resume-Tailor — build ATS-safe documents from tailored Markdown.
#
#   make setup                    one-time: create the venv + install python-docx
#   make export APP=<folder>      render resume.md + cover-letter.md in applications/<folder> to .docx + .pdf
#   make example                  export the bundled demo (applications/example-acme-backend)

PY := .venv/bin/python

.PHONY: setup export example

setup:
	python3 -m venv .venv && .venv/bin/pip install python-docx

export:
	@test -n "$(APP)" || { echo "usage: make export APP=<folder under applications/>"; exit 1; }
	$(PY) tools/build.py applications/$(APP)/resume.md applications/$(APP)/cover-letter.md

example:
	$(PY) tools/build.py applications/example-acme-backend/resume.md \
	                     applications/example-acme-backend/cover-letter.md
