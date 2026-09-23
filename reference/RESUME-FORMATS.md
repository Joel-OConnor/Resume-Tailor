# The resume file, and the optional two-column version

Every resume in this project renders from one Markdown source into `resume.docx` and `resume.pdf`.
That pair is the product: one file that a resume parser reads cleanly and a person enjoys reading.

## The resume — `resume.docx` / `resume.pdf`

Single column, top to bottom. Standard section headings. Real bullet lists. Contact details in the
document body, never in the header region. No tables, images, text boxes, or icons. Everything a
parser needs, by construction (see [ATS-PLAYBOOK.md](ATS-PLAYBOOK.md)).

Its typography is the user's own "2026 Polished Resume": Roboto throughout, a large light name, a
small semibold contact line, 15pt regular section headings, semibold role headings, an 11pt summary,
and a bullet glyph with a hanging indent on every accomplishment. The sizes and spacing were
measured from that PDF, so the export is that design with the current content, minus the columns.

**Send this one everywhere.** `resume.docx` is the most reliably parsed format, so it is the one to
upload to Workday, Greenhouse, Lever, Taleo, iCIMS and any "upload your resume" form; `resume.pdf`
is the same document for a form that only takes PDF, or for an email.

## The two-column version — `resume-polished.docx` / `resume-polished.pdf` (opt-in)

The same design in its original two-column arrangement: a narrow left rail carrying contact
details, skills and education beside a wide column carrying the name, summary and experience,
divided by a hairline rule. It is not produced by default; ask for it:

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

Keep rail entries short: the column is about 2.4 inches wide, so a long degree title will wrap
across three lines.

## Cover letters

A document with no `## ` sections is a letter, and a letter always renders single-column; asking
for `--layout both` still produces one file. Passing `--layout polished` explicitly forces a
two-column letter if you really want one.

## PDF fidelity

PDFs are produced by printing the layout's HTML through headless Chrome, so the text stays
selectable — an ATS can read the PDF as well as the Word file. If no Chromium-family browser is
installed, the exporter writes the `.html` next to the source instead and tells you; open it and
print to PDF by hand.

Both layouts are set in Roboto. The PDF pulls Roboto from Google Fonts while it prints, so it
embeds the design face even on a machine that has never installed it; offline it falls back to
Helvetica Neue / Helvetica / Arial, which are metric-similar — the layout holds, the letterforms
shift slightly. Word draws the `.docx` in Roboto only where the font is installed (free from Google
Fonts), and substitutes otherwise.
