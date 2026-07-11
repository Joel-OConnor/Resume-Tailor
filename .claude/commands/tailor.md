Tailor my resume to a specific job, following the method in CLAUDE.md exactly.

Job description:
$ARGUMENTS

If the job description above is empty, ask me to paste it (or tell you which file it's in).

Do all of this:
1. Analyze the job description: exact title + seniority, must-have requirements, nice-to-haves, the
   keywords/phrases it repeats, and the top day-to-day responsibilities.
2. Read `profile/MASTER_PROFILE.md` in full. (If it doesn't exist yet, tell me to build it first
   from `profile/raw/`.)
3. Map fit and gaps: strong matches, partial/adjacent matches, and genuine gaps.
4. Create `applications/<company>-<role>/` (lowercase slug) and write, selecting and reframing ONLY
   real experience from the profile:
   - `job-description.md` (the posting, saved for reference)
   - `resume.md` — following `templates/resume.md` structure precisely
   - `fit-report.md` — match strength, keywords covered vs. missing, honest ways to close gaps
   - `cover-letter.md` — following `templates/cover-letter.md`
   - `linkedin.md` — a headline + "About" tuned to this kind of role
5. Export the documents: `make export APP=<company>-<role>` (produces .docx + .pdf).
6. Summarize: overall match strength, what you emphasized and why, and any gaps I should be aware of
   — never fabricate anything; keep every claim true to my master profile.
