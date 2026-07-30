Tailor my resume to a specific job, following the method in CLAUDE.md exactly.

Job description:
$ARGUMENTS

If the job description above is empty, ask me to paste it (or tell you which file it's in).

Do all of this:
1. Analyze the job description: exact title + seniority, must-have requirements, nice-to-haves, the
   keywords/phrases it repeats, and the top day-to-day responsibilities.
2. Read `profile/master-profile.yaml` in full. (If it doesn't exist yet, tell me to build it first
   from `profile/raw/`.) Match the posting's wording against technology names *and* their aliases,
   and use `highlights[].tags` to find the strongest evidence for each requirement.
3. Map fit and gaps: strong matches, partial/adjacent matches, and genuine gaps.
4. Create `applications/<company>-<role>/` (lowercase slug) and write, selecting and reframing ONLY
   real experience from the profile:
   - `job-description.md` (the posting, saved for reference)
   - `resume.md` — following `templates/resume.md` structure precisely; use each highlight's `label`
     as the bullet's bold lead-in
   - `fit-report.md` — match strength, keywords covered vs. missing, honest ways to close gaps
   - `cover-letter.md` — following `templates/cover-letter.md`
   - `linkedin.md` — a headline + "About" tuned to this kind of role
5. Export: `make export APP=<company>-<role>`. This writes both layouts of the resume plus the
   cover letter.
6. Summarize: overall match strength, what you emphasized and why, any gaps I should be aware of,
   and which file to send where (`resume.docx` for portals, `resume-polished.docx` for people).

Never fabricate anything. Keep every claim true to my master profile, and flag rather than print
anything listed under the profile's `notes`.
