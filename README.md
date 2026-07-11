# Resume-Tailor

Craft a resume **tailored to a specific job** from one master record of your real background — so
the recruiter (and the automated screener behind them) sees the most obviously-qualified version of
a true resume, and you get more interviews.

You keep **one master profile** with everything you've ever done. Paste in a job description, and
Claude selects and reframes the most relevant parts into a focused, ATS-safe resume — plus a fit
report, a cover letter, and LinkedIn text — exported to **Word (.docx) and PDF**.

> It never invents experience. Tailoring is about *emphasis and framing of real facts*. A resume
> that wins an interview then falls apart in conversation helps no one.

## How to use it

**1. Add your background.** Drop anything into [`profile/raw/`](profile/raw/) — old resumes, a
LinkedIn profile export (PDF), brag docs, performance reviews, project write-ups. More is better.

**2. Build your master profile.** Open this folder in Claude Code and say:
> "Build my master profile from the files in profile/raw."

Claude fills in [`profile/MASTER_PROFILE.md`](profile/MASTER_PROFILE.md) — the single source of
truth. (You can also fill it in by hand; see [the guide](profile/HOW-TO-BUILD-YOUR-PROFILE.md).)

**3. Tailor to a job.** Paste a job description and say:
> "Tailor my resume for this job: <paste the LinkedIn description>"

or use the shortcut: `/tailor <paste the description>`.

**4. Get your documents.** Claude creates a folder under `applications/` with:

| File | What it is |
|------|-----------|
| `resume.md` / `.docx` / `.pdf` | Your tailored, ATS-safe resume |
| `fit-report.md` | How well you match, which keywords you cover vs. miss, and honest ways to close gaps |
| `cover-letter.md` / `.docx` / `.pdf` | A matching one-page cover letter |
| `linkedin.md` | A headline and "About" section tuned to this kind of role |

Review the resume, tweak anything, then re-export if needed.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install python-docx    # one-time (Chrome handles PDF)
# then, in Claude Code:  add files → "build my master profile" → "tailor for this job: …"
```

Convert a resume/letter to Word + PDF anytime:

```bash
make export APP=stripe-staff-backend-engineer     # exports every markdown in that folder
# or a single file:
.venv/bin/python tools/build.py applications/<folder>/resume.md
```

## Your privacy

Your actual data — `profile/` and `applications/` — is **gitignored** and never leaves your
machine. Only the templates, tooling, and docs are tracked, so you can safely put this under version
control or share it without exposing your history or drafts.

## Learn more

- [CLAUDE.md](CLAUDE.md) — the tailoring method Claude follows, step by step
- [reference/ATS-PLAYBOOK.md](reference/ATS-PLAYBOOK.md) — how resume screeners work and how to pass them
- [templates/](templates/) — the ATS-safe resume and cover-letter formats
