# Output

Everything the project writes lands here:

| Path | What it is | Written by |
|------|-----------|-----------|
| `master-profile.yaml` | **Your master profile**: your career as structured data, the single source of truth every document is drawn from. Hand edits welcome | `make profile` |
| `master-profile.md` | A readable view of the profile, to proofread. Generated, so edit the YAML instead | `.venv/bin/resume-tailor profile render` |
| `backups/` | Earlier profiles (`master-profile.<timestamp>.yaml`), kept whenever a rebuild or an answered question replaces the profile | `make profile`, and every recorded answer |
| `general/` | Your general resume and LinkedIn profile | `make resume` |
| `applications/<company>-<role>/` | A resume and cover letter for one job | `make tailor JOB=<posting>` |

**`general/`**, from `make resume`:

| File | What it is |
|------|-----------|
| `resume.docx` / `resume.pdf` | **Your general resume**: single column, parser-safe, one or two pages. Send it anywhere |
| `resume.md` | Its source |
| `linkedin.md` | Everything to put on LinkedIn, section by section and within LinkedIn's limits |

**`applications/<company>-<role>/`**, from `make tailor JOB=<posting>` (slug: lowercase company
and role, e.g. `stripe-staff-backend-engineer`):

| File | What it is |
|------|-----------|
| `resume.docx` / `resume.pdf` | **The resume tailored to that posting** |
| `cover-letter.docx` / `cover-letter.pdf` | A matching one-page cover letter |
| `resume.md` / `cover-letter.md` | Their sources |
| `job-description.md` | The posting, kept for reference |

Running a script again replaces its folder whole. To change what goes in, change the facts in
`master-profile.yaml` (or answer the review's questions) rather than editing the output; if you do
edit a `.md` by hand, re-render it with:

```bash
.venv/bin/resume-tailor build output/applications/<folder>/resume.md
```

`resume-tailor resume` and `resume-tailor tailor` take `--output DIR` to write somewhere else.

See [reference/RESUME-FORMATS.md](../reference/RESUME-FORMATS.md) for why the resume looks the way
it does, and [`examples/tailored-application/`](../examples/tailored-application/) for a worked
example (fictional).

**Everything here is gitignored** (it's your personal data): only this README is tracked.
