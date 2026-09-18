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

```bash
git clone <this repo> && cd Resume-Tailor
make setup                       # creates .venv and installs everything
cp .env.example .env             # then put your ANTHROPIC_API_KEY in it
```

**1. Add your background.** Drop anything into [`profile/raw/`](profile/raw/) — old resumes
(**PDF**, Word or text), a LinkedIn export, brag docs, performance reviews, project write-ups.
More is better.

**2. Build your master profile.**

```bash
make profile
```

That writes [`profile/master-profile.yaml`](templates/master-profile.example.yaml) — the single
source of truth. It names every file it read and every file it could not, so nothing goes missing
quietly, and it refuses to overwrite a profile you have already corrected (`make profile
FORCE=--force` replaces it, keeping a timestamped backup). Check it with `make profile-check`.

In Claude Code you can instead say *"Build my master profile from the files in profile/raw"*, or
start from `templates/master-profile.example.yaml` by hand — see
[the guide](profile/HOW-TO-BUILD-YOUR-PROFILE.md).

**3. Add the jobs.** Save each posting as a `.md` or `.txt` file in [`jobs/`](jobs/) — as many as
you like — then:

```bash
make tailor
```

Every posting is tailored in turn, each into its own folder. One failing does not stop the rest.
To do a single one: `make tailor JOB=jobs/stripe-staff-backend.md`.

In Claude Code, `/tailor <paste the posting>` runs the same method conversationally.

**4. Get your documents.** You get a folder under `applications/` per job, with:

| File | What it is |
|------|-----------|
| `resume.md` | The tailored resume source — edit here, then re-export |
| `resume.docx` / `resume.pdf` | **ATS-safe**, single column — upload this to application portals |
| `resume-polished.docx` / `.pdf` | **Two-column design** — email this to a person |
| `fit-report.md` (see `resume-tailor match`) | How well you match, keywords covered vs. missed, and honest ways to close gaps |
| `cover-letter.md` / `.docx` / `.pdf` | A matching one-page cover letter |
| `linkedin.md` | A headline and "About" section tuned to this kind of role |

Two layouts because a resume has to win twice: once with a parser, once with a person. The
single-column file is what survives a screener; the two-column one is what looks good in an inbox.
[Which to send when →](reference/RESUME-FORMATS.md)

## Two ways to run it

**Standalone** — no Claude Code needed. Bring your own Anthropic API key.

```bash
.venv/bin/resume-tailor profile build              # drafts master-profile.yaml from profile/raw/
.venv/bin/resume-tailor tailor                     # every posting in jobs/
.venv/bin/resume-tailor tailor path/to/posting.md  # or just one
```

That writes `applications/<company>-<role>/` per posting, with a resume, fit report, cover letter
and LinkedIn text, exported to `.docx` and `.pdf`.

Want to know how you match *before* spending a generation? That needs no API key at all:

```bash
.venv/bin/resume-tailor match jobs/stripe-staff-backend.md
```

Or run it as an HTTP API — the same code behind endpoints, ready for a UI:

```bash
.venv/bin/resume-tailor serve      # http://127.0.0.1:8000/docs
```

`GET /health`, `GET /profile`, `POST /match` need **no API key**. `POST /tailor` and
`GET /applications` do the generation.

**In Claude Code** — open the folder and talk to it. `/tailor <paste a job description>` runs the
same method conversationally, and you can correct the profile as you go.

Either way, **nothing is invented**: generated resumes are checked against your profile and
regenerated if they make a claim it does not support. See
[reference/ARCHITECTURE.md](reference/ARCHITECTURE.md).

## Quickstart

```bash
make setup && cp .env.example .env    # add your key to .env
make profile                          # after dropping files into profile/raw/
make tailor                           # after dropping postings into jobs/
```

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
| `make profile` | Draft it from `profile/raw/` (add `FORCE=--force` to replace one) |
| `make profile-check` | Validate it, and list anything still marked unconfirmed |
| `make profile-md` | Render a readable Markdown view at `profile/MASTER_PROFILE.md` |
| `make profile-schema` | Regenerate `schema/master-profile.schema.json` from the models |

The schema is generated from the code, so editors that understand `# yaml-language-server:` give you
autocomplete and inline validation while you edit.

## Your privacy

Your actual data — `profile/`, `jobs/` and `applications/` — is **gitignored** and never leaves your
machine, and so is `.env` with your API key. Only the templates, tooling, schema, and docs are
tracked, so you can fork this, push it, or share it without exposing your history, the jobs you are
looking at, or your drafts.

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
- [jobs/README.md](jobs/README.md) — dropping in postings to tailor against
- [templates/](templates/) — the resume, cover-letter, and profile formats
