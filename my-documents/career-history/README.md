# Drop your background materials here

Put anything about your career in this folder as PDF, Word (`.docx`), Markdown or plain text.
`make profile` reads every file here (not subfolders) to build your master profile,
`output/master-profile.yaml`. **The more you add, the better your tailored resumes will be.** This
folder is gitignored: nothing here is committed or shared.

Great things to add:

- **Old resumes**: every version you've kept, even outdated ones (they hold bullets you've forgotten).
- **LinkedIn export**: on your LinkedIn profile, *More → Save to PDF*.
- **A "brag doc" / accomplishments list**: any running notes of things you've done.
- **Performance reviews / self-reviews**: full of quantified wins in your own words.
- **Project write-ups, case studies, portfolios**: with outcomes and the tech used.
- **Job descriptions of roles you've held**: good reminders of your actual responsibilities.
- **Transcripts, certificates, award letters.**
- **Recommendations / peer feedback**: useful phrasing and proof points.

Don't worry about formatting or duplication: get it in here and run `make profile`. Building the
profile merges what repeats and drops what isn't a career fact. It names every file it read, and
every one it couldn't with the reason: a scanned PDF has no text in it, and an old `.doc` or an
`.rtf` isn't read at all, so add a text or Word (`.docx`) version of those instead.

`answers.md` is written by the tool: every question you've answered, during a profile build or a
review, is logged there. Leave it in place so the next rebuild keeps your answers.

Keeping your documents somewhere else? `.venv/bin/resume-tailor profile build --documents DIR`
builds from that folder instead, and logs your answers in `DIR/answers.md` so the next build from
there keeps them.
