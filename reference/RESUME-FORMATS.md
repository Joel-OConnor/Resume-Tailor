# Two layouts, and when to send which

Every resume in this project renders twice from the same Markdown source. They contain identical
words. They differ only in how those words are arranged — and that difference decides whether a
machine can read them.

## The ATS layout — `resume.docx` / `resume.pdf`

Single column, top to bottom. Standard section headings. Real bullet lists. Contact details in the
document body, never in the header region. No tables, images, text boxes, or icons.

**Send this to anything that isn't a person:** Workday, Greenhouse, Lever, Taleo, iCIMS, any
"upload your resume" form, any job board apply button. When in doubt, this one.

It looks plainer than the polished version. That is the point — a resume parser reads structure, not
design, and everything a designer would add is something a parser can lose.

## The polished layout — `resume-polished.docx` / `resume-polished.pdf`

Two columns divided by a hairline rule. A narrow left rail carries contact details, skills, and
education; the wide right column carries the name, summary, and experience. The name is set large
and light; accomplishments lead with a bold phrase rather than a bullet glyph.

**Send this to a person:** attached to an email to a recruiter or hiring manager, handed to a
referral, brought to a networking conversation, or posted somewhere a human will look at it.

**Do not upload it to an application portal.** Its two columns are a Word table. Most parsers read a
table in an order nobody intended — interleaving the rail into the middle of a job title, or
dropping it entirely. A resume that looks better and parses worse is a net loss.

## Which is "the real one"?

Both. They say the same true things about the same career. The ATS version optimises for the first
reader (software); the polished version optimises for the second (a person with ten seconds). Most
applications only ever meet the first, which is why the ATS layout keeps the plain `resume.docx`
name and the polished one is suffixed.

## Choosing at export time

```bash
.venv/bin/resume-tailor build applications/<folder>/resume.md                    # both (default)
.venv/bin/resume-tailor build applications/<folder>/resume.md --layout ats       # portal-safe
.venv/bin/resume-tailor build applications/<folder>/resume.md --layout polished  # design only
```

Cover letters render single-column: a document with no `## ` sections is a letter, so the
default skips the polished pass entirely. Passing `--layout polished` still forces one if you
really want it.

By default the polished layout puts **Skills**, **Technical Core**, **Core Competencies**,
**Education**, and **Certifications** in the left rail, and everything else in the main column.
Override it per export:

```bash
.venv/bin/resume-tailor build resume.md --layout polished --sidebar "Skills,Education,Languages"
```

Keep rail entries short: the column is about 2.4 inches wide, so a long degree title will wrap
across three lines.

## PDF fidelity

PDFs are produced by printing the layout's HTML through headless Chrome, so the text stays
selectable — an ATS can read the PDF as well as the Word file. If no Chromium-family browser is
installed, the exporter writes the `.html` next to the source instead and tells you; open it and
print to PDF by hand.

The polished layout is designed in Roboto (what the original design used). Without Roboto installed
it falls back to Helvetica Neue / Helvetica / Arial, which are metric-similar — the layout holds,
the letterforms shift slightly.
