# Job descriptions

Drop a job posting here as a `.md` or `.txt` file — one file per job, named however you like
(`stripe-staff-backend.md`, `acme.txt`). Then run:

```bash
.venv/bin/resume-tailor tailor
```

Every posting in this folder is tailored in turn, each into its own folder under
[`applications/`](../applications/) with a resume, fit report, cover letter and LinkedIn text.
One posting failing does not stop the others.

To tailor just one, name it:

```bash
.venv/bin/resume-tailor tailor jobs/stripe-staff-backend.md
```

Copy the posting in as plain text — the title and company on the first line help, and the
requirements matter far more than the benefits section:

```markdown
# Staff Backend Engineer — Stripe

**What you'll do**
- ...

**What we're looking for**
- ...
```

Want to know how you match before spending a generation? That needs no API key:

```bash
.venv/bin/resume-tailor match jobs/stripe-staff-backend.md
```

**Your postings here are gitignored** — only this README is tracked. Nothing you drop in this
folder is committed.
