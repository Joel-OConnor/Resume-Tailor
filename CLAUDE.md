# CLAUDE.md: Resume-Tailor

This project turns a machine-readable record of the user's real career into the documents a job
search needs, and gives each of them a review before the final files are written. The goal: the
most obviously qualified version of a *true* resume, readable by a recruiter and by the AI and
applicant-tracking parsers that screen for them.

## The whole workflow

There is one input step and two generating scripts. Nothing else generates anything.

```bash
make profile                         # 1. documents in profile/raw/  ->  profile/master-profile.yaml
make resume                          # 2. the general resume + the LinkedIn profile  ->  applications/general/
make tailor JOB=jobs/<posting>.md    # 3. a resume + cover letter for that one job   ->  applications/<company>-<role>/
```

All three call a model, chosen by `RESUME_TAILOR_LLM` in `.env`: the Anthropic API
(`anthropic`, with `ANTHROPIC_API_KEY`), or you, through the relay (`claude-code`, below). Steps 2
and 3 end the same way: a review that fixes and edits the drafts, then questions for the user, then
the final Word and PDF files. At a terminal the questions are asked as the script runs; with no terminal (including when
you run it from Claude Code) they are printed instead. See **The review step** below.

## 1. The master profile

`profile/master-profile.yaml` is the single source of truth. Every document is selected and
reframed from it and verified against it. It is validated against
`schema/master-profile.schema.json`; `resume-tailor profile render` writes a readable view to
`profile/MASTER_PROFILE.md` (generated, never edit it by hand).

`make profile` builds it from whatever the user dropped into `profile/raw/` (old resumes as PDF,
Word or text, a LinkedIn export, brag docs, and `answers.md`, the log of every question they
have answered). It runs in three passes:

1. **Draft.** A model records every distinct career fact from the documents as YAML.
2. **Refine.** A second pass reads the draft against its sources and a mechanical audit, and
   returns the same career recorded once, in the right place, with nothing irrelevant in it:
   duplicate highlights merged (keeping every figure), one entry per employer and per technology,
   accomplishments moved out of the skills list, each highlight under the role whose dates it
   fits, levels and years never claiming more than the documents show. It is checked by
   `verify/changes.py:check_refinement`, which rejects any refinement that adds a fact the draft
   did not have or loses one it did. If refinement cannot pass that check, the checked draft is
   written instead and the user is told.
3. **Settle what is open.** The audit (`review/profile.py`) reports what still needs a look, and
   every entry in `notes` (facts the documents left unclear) becomes a question. At a terminal
   they are asked right away and the answers are recorded in the profile.

It refuses to replace an existing profile without `FORCE=--force`, and keeps a timestamped
backup when it does: a profile may hold corrections made by hand. **Never regenerate an existing
profile without asking the user.** When they add new documents, the pattern is the same: drop
them in `profile/raw/` and rebuild.

When matching a posting's wording, use `technologies[].name` *and* `aliases`, and
`highlights[].tags` to find evidence. Anything in `notes` is **unconfirmed**: never print it.

## 2. The general resume and the LinkedIn profile

`make resume` writes `applications/general/`:

- `resume.md` / `resume.docx` / `resume.pdf`: one well-rounded resume aimed at the profile's
  target roles. Selected, not dumped: the strongest, most distinct accomplishments, a skills list
  of what recruiters for those roles screen for, one or two pages.
- `linkedin.md`: everything to put on LinkedIn, section by section in LinkedIn's own order and
  within its limits (headline 220 characters, About 2,600, each position 2,000, five top skills):
  headline, About, top skills, every position with a description and outcomes, education,
  certifications, skills, and Open to Work titles. It is checked by `review/linkedin.py` and by
  the same verifier as the resume.

## 3. A tailored application

`make tailor JOB=jobs/<posting>.md` takes exactly one job description the user points at, and
writes `applications/<company>-<role>/`:

- `resume.md` / `.docx` / `.pdf`: the resume tailored to that posting.
- `cover-letter.md` / `.docx` / `.pdf`: a one-page letter for it.
- `job-description.md`: the posting, kept for reference.

The terminal also shows a short fit summary (how strong the match is, the biggest gap), and the
posting's unsupported must-haves are the first questions in the review.

## The review step

Both scripts review what they wrote before anything is exported:

1. The mechanical fixes are applied (spacing, a missing full stop, a hyphen in a date range, a
   skill listed twice).
2. An editor pass tightens every document for readability without changing a fact, held to the
   same verifier as the draft.
3. The questions only the user can answer are gathered (an unsupported must-have, an outcome with
   no number, a missing date), at most eight, most important first.
4. At a terminal, each is asked. An answer that gives a fact is logged in `profile/raw/answers.md`
   and recorded in `profile/master-profile.yaml` (checked by `verify/changes.py:check_update`,
   which rejects anything the answers do not state), and the documents are revised to use it.
5. Then the final `.docx` and `.pdf` files are written.

**From Claude Code there is no terminal**, so the script finishes with the open questions printed.
Then *you* are the one who asks: put them to the user one at a time, record each real answer in
`profile/master-profile.yaml` where it belongs (a figure into the highlight it measures, a
technology into `technologies` and the role's stack, a new accomplishment as a highlight with a
label and tags), run `.venv/bin/resume-tailor profile validate`, and run the script again so the
final files use the answers. Never answer a question by guessing, and never record a "no".

## Answering the relay (`RESUME_TAILOR_LLM=claude-code`)

In this mode each model call becomes a file: the script writes `.relay/<id>.request.md` (a system
prompt and a prompt) and waits for `.relay/<id>.response.md`. You answer it:

1. Run `.venv/bin/resume-tailor relay wait` in the background. It exits as soon as a request is
   waiting and prints the request's path and the path to write the reply to.
2. Read the request in full. Write the complete reply, exactly in the shape its output contract
   asks for and nothing else (no preamble, no fences around a whole answer), to the reply path in
   one write.
3. Wait again, until the script finishes.

A reply is checked exactly like an API reply. When it fails a check, the next request opens with
the precise problems: fix every one. Everything in **Truthfulness** below applies to your replies
as it does to any model. To give up on a request, write the reason to `.relay/<id>.error.md`; the
script stops with that reason. Answered requests move to `.relay/answered/`.

## Doing it by hand

If there is no API key, or the user wants to shape a document conversationally, follow the same
steps yourself and hold your output to the same checks:

- Write the resume in `templates/resume.md`'s format (bold job title, plain company:
  `### **Senior Backend Engineer** – Northwind Payments`), and the cover letter in
  `templates/cover-letter.md`'s.
- Verify every document you write, and fix whatever it reports; never hand over a document it
  rejects:

  ```bash
  .venv/bin/python -c "from resume_tailor.profile import load; from resume_tailor.verify import verify_resume, format_violations; import pathlib; v = verify_resume(pathlib.Path('applications/<slug>/resume.md').read_text(), load()); print(format_violations(v) or 'clean')"
  ```

- Export with `.venv/bin/resume-tailor build applications/<slug>/resume.md` (and the cover letter).
- If you edit the profile, check your edit the way the scripts' edits are checked, e.g.
  `check_update(before, after, answers)` from `resume_tailor.verify.changes`.

## Truthfulness: non-negotiable

- **Never fabricate** employers, titles, dates, degrees, certifications, metrics, or skills the user
  does not have. A resume that gets an interview and then collapses in the conversation is worse
  than no interview. Tailoring is *emphasis and framing of real experience*, nothing more.
- If a **must-have is missing**, say so, and offer honest options (surface adjacent experience,
  add a true line, or treat it as a growth area). Do not paper over it.
- When you reframe a bullet, keep the underlying fact intact. If you are unsure a claim is true,
  ask the user rather than guess.

## Readable to people and to parsers

Every resume renders single-column, top to bottom, which is what AI and applicant-tracking parsers
read reliably (see `reference/ATS-PLAYBOOK.md` and `reference/RESUME-FORMATS.md`):

- Standard headings in the standard order (Summary, Skills, Experience, Education,
  Certifications, Projects), reverse-chronological, one date format.
- No tables, columns, text boxes, images or icons; contact details in the body, not a header.
- Arial throughout: body 10pt, headings 15pt, 0.6/0.7in margins. The job title is bold and the
  company is not.
- Use the posting's exact wording for skills the user really has, and spell out an acronym once
  ("Amazon Web Services (AWS)"); the profile's `aliases` exist for this. No hidden text, no
  keyword stuffing.

A two-column arrangement of the same design exists for emailing a person
(`resume-tailor build <resume.md> --layout polished`). Its columns are a Word table, which parsers
scramble, so **never point the user at a polished file for anything submitted through a form.**

## Working on the tooling

```bash
make setup     # one-time
make check     # ruff + mypy --strict + pytest with 100% coverage: all three must pass
```

- The package lives in `src/resume_tailor/`; tests mirror it in `tests/`. `agent/` holds every
  model operation and its prompts, `service/` the three runs, `review/` the mechanical reads,
  `verify/` the anti-fabrication checks, `render/` the Word and PDF output.
- **Coverage is enforced at 100%** and ruff's full rule set is on. New code needs tests, type
  annotations, and docstrings on public functions.
- Editing `src/resume_tailor/profile/models.py` changes the schema: run `make profile-schema`, or
  the test that pins `schema/master-profile.schema.json` will fail.
- A layout's `.docx` and its HTML-to-PDF render must stay visually identical. If you change one,
  change the other: they are the same document to the reader.

## Conventions

- The user's real data lives only in `profile/`, `jobs/` and `applications/`, all **gitignored**
  (as is `.env`), so personal info, the jobs they are looking at, and drafts never get committed.
- Application folder slugs: lowercase `company-role`, e.g. `stripe-staff-backend-engineer`.
- Resume Markdown must follow `templates/resume.md`'s structure so the renderers work.
