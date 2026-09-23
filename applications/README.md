# Applications

One folder per job you apply to (slug: lowercase `company-role`, e.g.
`stripe-staff-backend-engineer`). Each tailoring run creates a folder here with:

| File | What it is |
|------|-----------|
| `job-description.md` | The posting you pasted in (kept for reference) |
| `resume.md` | The tailored resume — edit here, then re-export |
| `resume.docx` / `resume.pdf` | **The resume** — single column, parser-safe, in the design's typography; send it anywhere (`--layout polished` adds a two-column version for people) |
| `fit-report.md` | Match strength, keywords covered vs. missing, honest ways to close gaps, and the readability review |
| `cover-letter.md` | Tailored one-page cover letter |
| `cover-letter.docx` / `.pdf` | Exports (single column) |
| `linkedin.md` | Suggested LinkedIn headline + "About" for this kind of role |

Everything but the Markdown is generated — see
[reference/RESUME-FORMATS.md](../reference/RESUME-FORMATS.md) for which resume to send where.

One folder is not a job: `general/` holds the untailored resume `make resume` renders from the
whole profile (just `resume.md` and its exports). Re-running replaces it.

**Your folders here are gitignored** (they contain personal data) — only this README and the
`example-acme-backend/` demo are tracked.

To fix a resume's easy problems, re-export it, and answer the questions it raises:

```bash
make review APP=stripe-staff-backend-engineer
```

To (re)generate the Word/PDF files after editing a resume or letter:

```bash
make export APP=stripe-staff-backend-engineer
```

See [`example-acme-backend/`](example-acme-backend/) for a complete worked example (fictional).
