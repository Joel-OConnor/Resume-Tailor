# Applications

One folder per job you apply to (slug: lowercase `company-role`, e.g.
`stripe-staff-backend-engineer`). Each tailoring run creates a folder here with:

| File | What it is |
|------|-----------|
| `job-description.md` | The posting you pasted in (kept for reference) |
| `resume.md` | The tailored resume — edit here, then re-export |
| `resume.docx` / `resume.pdf` | Submit-ready exports (generated; gitignored) |
| `fit-report.md` | Match strength, keywords covered vs. missing, honest ways to close gaps |
| `cover-letter.md` | Tailored one-page cover letter |
| `cover-letter.docx` / `.pdf` | Exports (generated; gitignored) |
| `linkedin.md` | Suggested LinkedIn headline + "About" for this kind of role |

**Your folders here are gitignored** (they contain personal data) — only this README and the
`example-acme-backend/` demo are tracked.

To (re)generate the Word/PDF files after editing a resume or letter:

```bash
make export APP=stripe-staff-backend-engineer
```

See [`example-acme-backend/`](example-acme-backend/) for a complete worked example (fictional).
