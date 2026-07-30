# Resume-Tailor

Craft a resume **tailored to a specific job** from one structured record of your real background —
so the recruiter (and the automated screener behind them) sees the most obviously-qualified version
of a true resume, and you get more interviews.

You keep **one master profile** as machine-readable YAML. Paste in a job description, and Claude
selects and reframes the most relevant parts into a focused resume — plus a fit report, a cover
letter, and LinkedIn text — exported to **Word and PDF in two layouts**: one built to survive an
applicant tracking system, one designed for a human to read.

> It never invents experience. Tailoring is about *emphasis and framing of real facts*. A resume
> that wins an interview then falls apart in conversation helps no one.

## How to use it

**1. Add your background.** Drop anything into [`profile/raw/`](profile/raw/) — old resumes, a
LinkedIn export, brag docs, performance reviews, project write-ups. More is better.

**2. Build your master profile.** Open this folder in Claude Code and say:

> "Build my master profile from the files in profile/raw."

Claude writes [`profile/master-profile.yaml`](templates/master-profile.example.yaml) — the single
source of truth. (You can also start from `templates/master-profile.example.yaml` by hand; see
[the guide](profile/HOW-TO-BUILD-YOUR-PROFILE.md).) Check it with `make profile-check`.

**3. Tailor to a job.** Paste a job description and say:

> "Tailor my resume for this job: \<paste the posting\>"

or use the shortcut `/tailor <paste the posting>`.

**4. Get your documents.** Claude creates a folder under `applications/` with:

| File | What it is |
|------|-----------|
| `resume.md` | The tailored resume source — edit here, then re-export |
| `resume.docx` / `resume.pdf` | **ATS-safe**, single column — upload this to application portals |
| `resume-polished.docx` / `.pdf` | **Two-column design** — email this to a person |
| `fit-report.md` | How well you match, keywords covered vs. missed, and honest ways to close gaps |
| `cover-letter.md` / `.docx` / `.pdf` | A matching one-page cover letter |
| `linkedin.md` | A headline and "About" section tuned to this kind of role |

Two layouts because a resume has to win twice: once with a parser, once with a person. The
single-column file is what survives a screener; the two-column one is what looks good in an inbox.
[Which to send when →](reference/RESUME-FORMATS.md)

## Quickstart

```bash
make setup
```

Then, in Claude Code: add files → "build my master profile" → "tailor for this job: …"

Export a resume or letter to Word + PDF anytime:

```bash
make export APP=stripe-staff-backend-engineer
```

Or a single file, with control over the layout:

```bash
.venv/bin/resume-tailor build applications/<folder>/resume.md --layout ats
```

## The master profile

Your career lives in `profile/master-profile.yaml` as structured data, not prose — so both Claude
and the tooling can query it precisely instead of re-reading paragraphs:

```yaml
technologies:
  - group: Backend & Cloud
    items:
      - name: Amazon Web Services (AWS)
        aliases: [AWS]              # screeners search for either spelling
        level: proficient
        years: 6
        used_at: [charter-communications]

experience:
  - id: charter-communications
    company: Charter Communications
    roles:
      - title: Lead Software Engineer
        start: 2022-06
        end: present
        highlights:
          - label: Platform Modernization
            text: Architected and embedded AI-driven developer tooling across the SDLC…
            tags: [ai, developer productivity, sdlc]
```

| Command | What it does |
|---|---|
| `make profile-check` | Validate it, and list anything still marked unconfirmed |
| `make profile-md` | Render a readable Markdown view at `profile/MASTER_PROFILE.md` |
| `make profile-schema` | Regenerate `schema/master-profile.schema.json` from the models |

The schema is generated from the code, so editors that understand `# yaml-language-server:` give you
autocomplete and inline validation while you edit.

## Your privacy

Your actual data — `profile/` and `applications/` — is **gitignored** and never leaves your machine.
Only the templates, tooling, schema, and docs are tracked, so you can safely put this under version
control or share it without exposing your history or drafts.

## Developing

```bash
make check     # ruff (full rule set) + mypy --strict + pytest at 100% coverage
make format    # auto-fix and reformat
```

Source is in `src/resume_tailor/`, tests mirror it in `tests/`. All three gates run in CI.

## Learn more

- [CLAUDE.md](CLAUDE.md) — the tailoring method Claude follows, step by step
- [reference/RESUME-FORMATS.md](reference/RESUME-FORMATS.md) — the two layouts and when to send which
- [reference/ATS-PLAYBOOK.md](reference/ATS-PLAYBOOK.md) — how resume screeners work and how to pass them
- [profile/HOW-TO-BUILD-YOUR-PROFILE.md](profile/HOW-TO-BUILD-YOUR-PROFILE.md) — filling in your profile
- [templates/](templates/) — the resume, cover-letter, and profile formats
