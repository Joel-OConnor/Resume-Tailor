Tailor my resume and cover letter to one job, following the workflow in CLAUDE.md exactly.

Job description:
$ARGUMENTS

If the job description above is empty, ask me to paste it or tell you which file it's in.

Do all of this:
1. If I pasted the posting, save it as `jobs/<company>-<role>.md` (lowercase slug). If I named a
   file, use that file.
2. Make sure `profile/master-profile.yaml` exists. If it doesn't, tell me to run `make profile`
   first and stop.
3. Run `make tailor JOB=<that file>`. It writes `applications/<company>-<role>/` with the tailored
   resume and cover letter, and prints a fit summary and the review's open questions.
4. Tell me the fit summary in a sentence or two. Then ask me the open questions one at a time.
   For each real answer, record the fact in `profile/master-profile.yaml` where it belongs (a
   figure into the highlight it measures, a technology into `technologies` and the role's stack,
   a new accomplishment as a highlight with a label and tags), and run
   `.venv/bin/resume-tailor profile validate`. Record nothing for a "no" or a skip, and never
   answer a question yourself.
5. If I gave any answers, run `make tailor JOB=<that file>` again so the final files use them.
6. Summarize: how strong the match is, what the resume leads with and why, any gaps I should know
   about, and that `resume.docx` is the file to upload (the PDF is for forms that only take PDF,
   or for email).

If there's no API key, do steps 3 to 5 by hand as CLAUDE.md's "Doing it by hand" describes, and
verify every document before handing it over.

Never fabricate anything. Keep every claim true to my master profile, and never print anything
listed under the profile's `notes`.
