# CLAUDE.md — Resume-Tailor

This project helps craft a **resume tailored to a specific job description**, built from a master
record of the user's real background. The goal: give a recruiter (and the automated screener behind
them) the most obviously-qualified version of a *true* resume, to raise the odds of an interview.

**You (Claude) are the engine.** When the user gives you a job description, you follow the method
below to produce a tailored resume + supporting docs, then export them to Word and PDF.

## The two moving parts

1. **`profile/MASTER_PROFILE.md` — the single source of truth.** A *superset* of everything the user
   has done: every role, every accomplishment, every skill and tool — far more than fits on one
   resume. Tailoring never invents; it **selects and reframes** from this file. Help the user build
   and grow it from the raw materials in `profile/raw/` (see `profile/HOW-TO-BUILD-YOUR-PROFILE.md`).

2. **`applications/<company>-<role>/` — one folder per job.** Each tailoring run writes its outputs
   here (job description, tailored resume, fit report, cover letter, LinkedIn text, and the exported
   `.docx`/`.pdf`).

## The tailoring method (follow every step)

When the user provides a job description (pasted, or dropped in a file):

1. **Analyze the job description.** Extract and note:
   - the exact **job title** and seniority level;
   - **must-have** requirements (skills, tools, years, degrees, domain);
   - **nice-to-haves**;
   - the **keywords and phrases** the posting repeats (these are what the screener matches on);
   - the **top responsibilities** — what this person will actually do day to day;
   - the **company/industry** context and any values/tone signals.

2. **Read `profile/MASTER_PROFILE.md`** in full.

3. **Map fit and find gaps.** For each must-have, find the strongest *real* evidence in the profile.
   Build three lists: **strong matches**, **partial/adjacent matches**, and **genuine gaps** (things
   the JD wants that the profile doesn't support).

4. **Select and reframe (truthfully).** Compose the resume by:
   - **Leading with what matches.** Order experience and skills so the most relevant items are seen
     first (top of page, top of each section).
   - **Mirroring the JD's language** for skills the user *genuinely has*. If the JD says
     "Kubernetes" and the profile says "K8s," write "Kubernetes." If the JD's title is "Staff
     Software Engineer," reflect that framing in the summary when it's honest to do so.
   - **Rewriting bullets** to foreground the results the JD cares about, keeping every claim true.
     Prefer strong verb + what you did + measurable outcome. Keep real metrics; never invent them.
   - **Writing a targeted 2–3 line summary** naming the target role and the top 3–4 matched
     strengths.
   - **Cutting** low-relevance content so the page stays focused (it still lives in the master file).

5. **Produce the outputs** in `applications/<company>-<role>/`:
   - `resume.md` — the tailored resume (follow `templates/resume.md` exactly, so it exports cleanly).
   - `fit-report.md` — how strongly the user matches, JD keywords covered vs. missing, and honest,
     actionable ways to close gaps (adjacent experience to highlight, a line to add if true, or a
     skill worth learning). **Never** suggest fabricating.
   - `cover-letter.md` — a focused one-page letter (follow `templates/cover-letter.md`).
   - `linkedin.md` — a headline + "About" section tuned to this kind of role.

6. **Export** with `make export APP=<company>-<role>` (or run `tools/build.py` on a file). This
   writes ATS-safe `.docx` and `.pdf` versions of the resume and cover letter next to the markdown.

7. **Summarize for the user**: the match strength, what you emphasized and why, any gaps they should
   be aware of, and where the files are.

## Truthfulness — non-negotiable

- **Never fabricate** employers, titles, dates, degrees, certifications, metrics, or skills the user
  doesn't have. A resume that gets an interview then collapses in the conversation is worse than no
  interview. Tailoring = *emphasis and framing of real experience*, nothing more.
- If a **must-have is missing**, say so in the fit report and offer honest options (surface adjacent
  experience, add a true line, or note it as a growth area) — do not paper over it.
- When you reframe a bullet, keep the underlying fact intact. If you're unsure a claim is true,
  ask the user rather than guess.

## Beating the automated screener — the honest way

Modern hiring runs resumes through Applicant Tracking Systems (ATS) and, increasingly, AI ranking.
Getting past them is about making genuine fit **legible to a parser**, not tricking it. See
`reference/ATS-PLAYBOOK.md` for the full rules; the essentials:

- **Clean, single-column, standard-heading layout** (Summary, Skills, Experience, Education). No
  tables, columns, text boxes, images, or header/footer regions — parsers drop or scramble those.
  `tools/build.py` produces a compliant `.docx` by construction.
- **Keyword alignment done truthfully:** use the JD's exact wording for skills the user really has;
  spell out an acronym once with its expansion (e.g., "Applicant Tracking System (ATS)").
- **No deceptive tricks** — no hidden white-text keyword stuffing, no fake sections. ATS and
  recruiters detect these and blacklist candidates. We win on real, well-surfaced fit.

## Conventions

- The user's real data lives only in `profile/` and `applications/` — both are **gitignored** so
  personal info and drafts never get committed. The templates, tooling, and docs are what's tracked.
- Application folder slugs: lowercase `company-role`, e.g. `stripe-staff-backend-engineer`.
- Resume markdown must follow `templates/resume.md`'s structure so `tools/build.py` renders it
  correctly. When in doubt, copy the template and fill it in.
