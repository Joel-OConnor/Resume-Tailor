# CLAUDE.md — Resume-Tailor

This project builds a **resume tailored to a specific job description** from a machine-readable
record of the user's real background. The goal: give a recruiter (and the automated screener behind
them) the most obviously-qualified version of a *true* resume, to raise the odds of an interview.

**You (Claude) are the engine.** When the user gives you a job description, follow the method below
to produce a tailored resume plus supporting docs, then export them to Word and PDF.

## The three moving parts

1. **`profile/master-profile.yaml` — the single source of truth.** A structured *superset* of
   everything the user has done: every employer, role, accomplishment, technology. Tailoring never
   invents; it **selects and reframes** from this file. It is validated against
   `schema/master-profile.schema.json`, and `make profile-md` renders a readable Markdown view at
   `profile/MASTER_PROFILE.md` (generated — never edit it by hand).

2. **`jobs/` — the inbox, and `applications/<company>-<role>/` — one folder per job.** The user
   drops postings into `jobs/` as `.md` or `.txt` files (as many as they like); each tailoring run
   writes its outputs to `applications/<slug>/` (job description, tailored resume, fit report,
   cover letter, LinkedIn text, exports). Both are gitignored.

3. **`src/resume_tailor/` — the tooling.** A tested Python package that parses the tailored Markdown
   and renders it into two layouts (below). Run `make check` after touching it.

## One layout, one source

Every resume renders from its Markdown into `resume.docx` and `resume.pdf`: a single column with
standard headings, no tables, and the typography of the user's own designed resume (Roboto, a
large light name, 15pt headings, glyph bullets). That one file goes to portals and to people alike.

A two-column arrangement of the same design (`resume-polished.docx` / `.pdf`) exists for emailing
a person and is opt-in: `--layout polished`. Its columns are a Word table, and resume parsers
scramble tables, so **never point the user at a polished file for anything submitted through a
form.** See `reference/RESUME-FORMATS.md`.

## A general resume, untailored

When the user wants a plain, well-rounded resume with no posting in mind, do not tailor: run

```bash
make resume            # or: .venv/bin/resume-tailor general [--title ..] [--max-highlights N] [--max-skills N] [--since YYYY]
```

It renders the whole profile into `applications/general/` (Word and PDF, no API key): every
employer and bullet in profile order, and every technology recorded above `exposure`/`working`.
It is deterministic and cannot invent anything, so it needs no verification pass. Shape it with
the caps rather than by editing the output; anything worth keeping belongs in the profile.

## The tailoring method (follow every step)

When the user provides a job description — pasted, dropped in a file, or sitting in `jobs/`. If
they say "tailor my resume" without naming one, look in `jobs/` and tell them what you found. For
several postings, do each one in full before starting the next; a failure on one is reported and
the rest still run.

1. **Analyze the job description.** Extract and note:
   - the exact **job title** and seniority level;
   - **must-have** requirements (skills, tools, years, degrees, domain);
   - **nice-to-haves**;
   - the **keywords and phrases** the posting repeats (these are what the screener matches on);
   - the **top responsibilities** — what this person will actually do day to day;
   - the **company/industry** context and any values/tone signals.

2. **Read `profile/master-profile.yaml` in full.** (If it doesn't exist, tell the user to run
   `make profile` to build it from `profile/raw/` — see `profile/HOW-TO-BUILD-YOUR-PROFILE.md`.
   Never regenerate an existing profile without asking: it may hold corrections made by hand, and
   `profile build` refuses to replace one without `--force` for exactly that reason.) Use `technologies[].name`
   *and* `aliases` when matching the posting's wording, `highlights[].tags` to find evidence for a
   requirement, and `notes` to see what the user still has to confirm.

3. **Map fit and find gaps.** Start with the deterministic pass:

   ```bash
   .venv/bin/resume-tailor match <job-description.md> --format markdown
   ```

   It reports, with evidence, which of the profile's technologies the posting asks for and what it
   asks for that the profile does not support. Treat it as the floor, not the ceiling: it only
   reads `technologies[]`, so read `highlights[]` yourself for everything it cannot see.

   **Never promote one of its `qualified` matches to a confirmed claim without asking the user.** A
   match is qualified precisely because it is a category alias, a stem match, an unconfirmed
   `notes[]` entry, or a technology with no accomplishment behind it.

   Then, from that plus your own reading, build three lists: **strong matches**,
   **partial/adjacent matches**, and **genuine gaps** (things the JD wants that the profile
   doesn't support).

4. **Select and reframe (truthfully).** Compose the resume by:
   - **Leading with what matches.** Order experience and skills so the most relevant items are seen
     first (top of page, top of each section).
   - **Mirroring the JD's language** for skills the user *genuinely has*. If the JD says
     "Kubernetes" and the profile lists it under the alias "K8s," write "Kubernetes." If the JD's
     title is "Staff Software Engineer," reflect that framing in the summary when it's honest to do
     so.
   - **Rewriting bullets** to foreground the results the JD cares about, keeping every claim true.
     Prefer strong verb + what you did + measurable outcome. Keep real metrics; never invent them.
     Use a highlight's `label` as the bullet's bold lead-in (`- **Data Layer Design:** …`).
   - **Writing a targeted 2–3 line summary** naming the target role and the top 3–4 matched
     strengths.
   - **Cutting** low-relevance content so the page stays focused (it still lives in the profile).

5. **Produce the outputs** in `applications/<company>-<role>/`:
   - `job-description.md` — the posting, saved for reference.
   - `resume.md` — the tailored resume, following `templates/resume.md` exactly.
   - `fit-report.md` — how strongly the user matches, JD keywords covered vs. missing, and honest,
     actionable ways to close gaps (adjacent experience to highlight, a line to add if true, or a
     skill worth learning). **Never** suggest fabricating.
   - `cover-letter.md` — a focused one-page letter, following `templates/cover-letter.md`.
   - `linkedin.md` — a headline + "About" section tuned to this kind of role.

6. **Export** with `make export APP=<company>-<role>`. The resume and the cover letter each render
   to `.docx` and `.pdf`.

   (The standalone path does all of steps 5 and 6 in one command: `make tailor`, or
   `.venv/bin/resume-tailor tailor <posting>`. Use it when the user wants the whole inbox done at
   once; work through the method by hand when they want to shape the result as you go.)

7. **Summarize for the user**: the match strength, what you emphasized and why, any gaps they should
   be aware of, that `resume.docx` is the file to submit, and where everything lives.

## Checking your own work

The standalone path enforces truthfulness mechanically, and you are held to the same standard.
After writing `resume.md`, verify it the way the agent path does:

```bash
.venv/bin/python -c "from resume_tailor.profile import load; from resume_tailor.verify import verify_resume, format_violations; import pathlib; v = verify_resume(pathlib.Path('applications/<slug>/resume.md').read_text(), load()); print(format_violations(v) or 'clean')"
```

It checks every employer, title, date, education entry, technology and **metric** against the
profile. If it reports a violation, fix the resume — do not argue with it and do not hand over a
document it rejects. Then give it the second read described below.

## Reviewing what you wrote

Every generated resume gets a second read before it is handed over. After `resume.md` verifies
clean, run:

```bash
.venv/bin/resume-tailor review applications/<slug>/resume.md --export
```

It applies the mechanical fixes itself (spacing, a missing full stop, a hyphen in a date range,
a skill listed twice) and re-exports, then prints two lists. **Suggestions** are an editor's
calls — a bullet over 40 words, bullets that switch tense within a role, a phrase repeated,
"responsible for", filler — and in Claude Code *you* are the editor: rewrite for them, keeping
every fact, and run the verifier again. **Questions** are gaps only the user can fill — an
accomplishment with no outcome, a role with no numbers, missing dates. Ask them one at a time,
put each answer into `profile/master-profile.yaml` (a highlight, a scope, a corrected date),
then regenerate and review again. Never answer a question by guessing.

The standalone path does the same mechanically: `tailor` applies the fixes and has the model
edit the draft for readability under the same verifier, and `review --interactive` walks the
questions with the user and keeps the answers in `profile/raw/answers.md`, where the next
`make profile FORCE=--force` picks them up as source material.

## Truthfulness — non-negotiable

- **Never fabricate** employers, titles, dates, degrees, certifications, metrics, or skills the user
  doesn't have. A resume that gets an interview then collapses in the conversation is worse than no
  interview. Tailoring = *emphasis and framing of real experience*, nothing more.
- If a **must-have is missing**, say so in the fit report and offer honest options (surface adjacent
  experience, add a true line, or note it as a growth area) — do not paper over it.
- When you reframe a bullet, keep the underlying fact intact. If you're unsure a claim is true,
  ask the user rather than guess. Anything listed under the profile's `notes` is **unconfirmed** —
  raise it rather than printing it.

## Beating the automated screener — the honest way

Modern hiring runs resumes through Applicant Tracking Systems (ATS) and, increasingly, AI ranking.
Getting past them is about making genuine fit **legible to a parser**, not tricking it. See
`reference/ATS-PLAYBOOK.md` for the full rules; the essentials:

- **Clean, single-column, standard-heading layout** (Summary, Skills, Experience, Education) for
  anything submitted through a portal. No tables, columns, text boxes, images, or header/footer
  regions — parsers drop or scramble those. The ATS layout is compliant by construction.
- **Keyword alignment done truthfully:** use the JD's exact wording for skills the user really has;
  spell out an acronym once with its expansion (e.g., "Applicant Tracking System (ATS)"). The
  profile's `aliases` field exists for exactly this.
- **No deceptive tricks** — no hidden white-text keyword stuffing, no fake sections. ATS and
  recruiters detect these and blacklist candidates. We win on real, well-surfaced fit.

## Working on the tooling

```bash
make setup     # one-time
make check     # ruff + mypy --strict + pytest with 100% coverage — all three must pass
```

- The package lives in `src/resume_tailor/`; tests mirror it in `tests/`.
- **Coverage is enforced at 100%** and ruff's full rule set is on. New code needs tests, type
  annotations, and docstrings on public functions.
- Editing `src/resume_tailor/profile/models.py` changes the schema: run `make profile-schema`, or the test that pins
  `schema/master-profile.schema.json` will fail.
- A layout's `.docx` and its HTML-to-PDF render must stay visually identical. If you change one,
  change the other — they are the same document to the reader.

## Conventions

- The user's real data lives only in `profile/`, `jobs/` and `applications/` — all three are
  **gitignored** (as is `.env`) so personal info, the jobs they are looking at, and drafts never get
  committed. Templates, tooling, schema, and docs are tracked.
- Application folder slugs: lowercase `company-role`, e.g. `stripe-staff-backend-engineer`.
- Resume Markdown must follow `templates/resume.md`'s structure so the renderers work. When in
  doubt, copy the template and fill it in.
