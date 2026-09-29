# Resume-Tailor

Turn your real career history into the documents a job search needs: a general resume, a LinkedIn
profile, and a resume and cover letter tailored to any job you point it at. Every document is read
by a recruiter *and* by the AI and applicant-tracking parsers that screen for them, so each one is
written to work for both.

> It never invents experience. Every document is drawn from one record of your real history and
> checked against it before it is written. A resume that wins an interview and then falls apart
> in the conversation helps no one.

## Setup

```bash
git clone <this repo> && cd Resume-Tailor
make setup                       # creates .venv and installs everything
cp .env.example .env
```

Then choose who answers the scripts, with `RESUME_TAILOR_LLM` in `.env`:

- **`anthropic`**: the scripts call the Anthropic API with your `ANTHROPIC_API_KEY`, billed per
  token. `RESUME_TAILOR_MODEL` picks the model and `RESUME_TAILOR_EFFORT` how hard it thinks;
  `.env.example` lists the options and their prices.
- **`claude-code`**: no key and no API bill. Each request is written to `.relay/` and the script
  waits while a Claude Code session in this folder answers it. Run the script, then ask Claude to
  "answer the relay". Every reply goes through the same checks an API reply does.

## How to use it

**1. Build your master profile.** Drop anything about your career into
[`profile/raw/`](profile/raw/): old resumes (PDF, Word or text), a LinkedIn export, brag docs,
performance reviews. Then:

```bash
make profile
```

It drafts `profile/master-profile.yaml` from everything it can read, then **refines** it: the same
accomplishment told by two documents is recorded once, each accomplishment sits under the role it
belongs to, noise and accomplishments-posing-as-skills are dropped, and levels and years never
claim more than your documents show. The refinement is checked mechanically, so it can merge and
tidy but can never add a fact or lose one. Anything it could not settle becomes a question, asked
right there; your answers go into the profile.

It names every file it read and every file it could not. It will not replace a profile you have
already corrected unless you say so (`make profile FORCE=--force`, which keeps a backup). Added
new documents later? Drop them in `profile/raw/` and rebuild.

**2. Your general resume and LinkedIn profile.**

```bash
make resume
```

Writes `applications/general/`:

| File | What it is |
|---|---|
| `resume.docx` / `resume.pdf` | One well-rounded resume aimed at your target roles: your strongest, most distinct work, one or two pages |
| `linkedin.md` | Everything to put on LinkedIn, section by section and within LinkedIn's limits: headline, About, top skills, every position, education, certifications, skills, Open to Work titles |

**3. A resume and cover letter for one job.** Save the posting as a `.md` or `.txt` file (in
[`jobs/`](jobs/) is a good place) and point at it:

```bash
make tailor JOB=jobs/stripe-staff-backend.md
```

Writes `applications/<company>-<role>/` with `resume.docx` / `resume.pdf` tailored to that
posting, `cover-letter.docx` / `cover-letter.pdf`, and the posting itself for reference. It also
tells you how strong the match is and where the gaps are.

### The review before the final files

Steps 2 and 3 review what they wrote before any Word or PDF file exists:

1. Mechanical problems are fixed (spacing, punctuation, date ranges, a skill listed twice).
2. An editor pass tightens every document for readability, under the same no-invention check.
3. You get the questions only you can answer: a must-have the posting asks for that your profile
   never mentions, an accomplishment with no outcome, a missing date. At most eight, most
   important first. Answer in a sentence, press Enter to skip, type `done` to finish.
4. Your answers go into your master profile (and a log in `profile/raw/answers.md`), the
   documents are revised to use them, and *then* the final files are written.

Run without a terminal (in CI, or from Claude Code) and it skips the asking: the final files are
written and the open questions are printed, so you can add the facts to your profile and run it
again.

## Which file to send

`resume.docx` is the one to upload to any application portal (Workday, Greenhouse, Lever...):
Word files are the most reliably parsed format. `resume.pdf` is the same document for a form that
only takes PDF, or for an email. Both are single-column, standard headings, no tables or graphics,
contact details in the body, set in Arial. [Why that layout →](reference/RESUME-FORMATS.md)

Edited a `.md` by hand? Re-render it with `.venv/bin/resume-tailor build <file.md>`.

## In Claude Code

Open the folder and ask. *"Build my master profile"*, *"make my general resume"* and *"tailor my
resume to jobs/acme.md"* run the same scripts; Claude then asks you the review's questions in the
chat, records your answers in the profile, and reruns the script for the final files. `/tailor`
does the tailoring step directly.

## The master profile

Your career lives in `profile/master-profile.yaml` as structured data, not prose, so every
document can be drawn from it precisely and checked against it:

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

`resume-tailor profile validate` checks it and lists what its audit still flags;
`resume-tailor profile render` writes a readable copy to `profile/MASTER_PROFILE.md`. The schema is
generated from the code, so an editor that understands `# yaml-language-server:` autocompletes
and validates it as you type. See [the guide](profile/HOW-TO-BUILD-YOUR-PROFILE.md).

## Your privacy

Your data (`profile/`, `jobs/` and `applications/`) is **gitignored** and never leaves your
machine except in the requests to the model, and so is `.env` with your API key. Only the
templates, tooling, schema and docs are tracked.

## Developing

```bash
make check     # ruff (full rule set) + mypy --strict + pytest at 100% coverage
make format    # auto-fix and reformat
```

Source is in `src/resume_tailor/`, tests mirror it in `tests/`. All three gates run in CI.
[How it fits together →](reference/ARCHITECTURE.md)

## Learn more

- [CLAUDE.md](CLAUDE.md): the workflow and rules Claude follows
- [reference/RESUME-FORMATS.md](reference/RESUME-FORMATS.md): the resume layout, and why
- [reference/ATS-PLAYBOOK.md](reference/ATS-PLAYBOOK.md): how resume screeners work and how to pass them honestly
- [profile/HOW-TO-BUILD-YOUR-PROFILE.md](profile/HOW-TO-BUILD-YOUR-PROFILE.md): building and keeping your profile
- [templates/](templates/): the resume, cover-letter and profile formats
