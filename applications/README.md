# Applications

Everything the two generating scripts write lands here, one folder per run.

**`general/`**, from `make resume`:

| File | What it is |
|------|-----------|
| `resume.docx` / `resume.pdf` | **Your general resume**: single column, parser-safe, one or two pages. Send it anywhere |
| `resume.md` | Its source |
| `linkedin.md` | Everything to put on LinkedIn, section by section and within LinkedIn's limits |

**`<company>-<role>/`**, from `make tailor JOB=<posting>` (slug: lowercase company and role, e.g.
`stripe-staff-backend-engineer`):

| File | What it is |
|------|-----------|
| `resume.docx` / `resume.pdf` | **The resume tailored to that posting** |
| `cover-letter.docx` / `cover-letter.pdf` | A matching one-page cover letter |
| `resume.md` / `cover-letter.md` | Their sources |
| `job-description.md` | The posting, kept for reference |

Running a script again replaces its folder whole. To change what goes in, change the facts in
`profile/master-profile.yaml` (or answer the review's questions) rather than editing the output;
if you do edit a `.md` by hand, re-render it with:

```bash
.venv/bin/resume-tailor build applications/<folder>/resume.md
```

See [reference/RESUME-FORMATS.md](../reference/RESUME-FORMATS.md) for why the resume looks the way
it does, and [`example-acme-backend/`](example-acme-backend/) for a worked example (fictional).

**Your folders here are gitignored** (they contain personal data): only this README and the
example are tracked.
