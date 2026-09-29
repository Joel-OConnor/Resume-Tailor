# The resume file, and the optional two-column version

Every resume in this project renders from one Markdown source into `resume.docx` and `resume.pdf`.
That pair is the product: one file that an AI or applicant-tracking parser reads cleanly and a
person can skim in ten seconds.

## The resume: `resume.docx` / `resume.pdf`

The layout follows the guidance that holds across recruiters, parser vendors and career services:
a single-column, text-first, reverse-chronological resume with clean type and room to breathe.

**For the parser**

- **Single column, top to bottom.** A two-column layout gets read straight across the page, so
  the columns interleave into nonsense.
- **Standard headings:** Summary, Skills, Experience, Education, Certifications, Projects. A
  parser looks for those words; it cannot find "Where I've Made Magic".
- **No tables, text boxes, icons, logos, charts or images.** Parsers skip or scramble them.
- **Contact details in the body**, on one line under the name, never in the page header or
  footer, which many parsers ignore.
- **Real text, exported as `.docx` or a text-based PDF**, never an image.

**For the person**

- **Arial throughout**, a clean sans-serif installed on every Mac and Windows machine, so the
  `.docx` looks the same wherever a recruiter opens it and the PDF embeds it.
- **A clear hierarchy:** a 28pt name, 15pt section headings, 10pt body with an 11pt summary, a
  10pt contact line.
- **One weight per idea:** each role's heading bolds the job title and leaves the company plain
  (`### **Senior Backend Engineer** – Northwind Payments`), so a skim follows the career.
- **0.6in top and bottom, 0.7in side margins**, and a bullet glyph with a hanging indent on
  every accomplishment.

**Send this one everywhere.** `resume.docx` is the most reliably parsed format, so it is the one to
upload to Workday, Greenhouse, Lever, Taleo, iCIMS and any "upload your resume" form. `resume.pdf`
is the same document for a form that only takes PDF, or for an email.

## The two-column version: `resume-polished.docx` / `resume-polished.pdf` (opt-in)

The same typography in a two-column arrangement: a narrow left rail carrying contact details,
skills and education beside a wide column carrying the name, summary and experience, divided by a
hairline rule. Neither script produces it; render it from a resume when you want it:

```bash
.venv/bin/resume-tailor build applications/<folder>/resume.md --layout polished   # two-column only
.venv/bin/resume-tailor build applications/<folder>/resume.md --layout both       # the pair
```

**Do not upload it to an application portal.** Its two columns are a Word table. Most parsers read
a table in an order nobody intended, interleaving the rail into the middle of a job title or
dropping it entirely. Hand it to a person, if at all.

By default it puts **Skills**, **Technical Core**, **Core Competencies**, **Education** and
**Certifications** in the left rail and everything else in the main column. Override it per export:

```bash
.venv/bin/resume-tailor build resume.md --layout polished --sidebar "Skills,Education,Languages"
```

Keep rail entries short: the column is about 2.4 inches wide, so a long degree title will wrap.

## Cover letters

A document with no `## ` sections is a letter, and a letter always renders single-column; asking
for `--layout both` still produces one file. Passing `--layout polished` explicitly forces a
two-column letter if you really want one.

## PDF fidelity

PDFs are produced by printing the layout's HTML through headless Chrome, so the text stays
selectable: a parser reads the PDF as well as the Word file. If no Chromium-family browser is
installed, the exporter writes the `.html` next to the source instead and tells you; open it and
print to PDF by hand. Arial is a system font, so printing needs no network.
