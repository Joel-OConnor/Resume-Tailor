# ATS Playbook — getting past resume screeners (honestly)

Most applications are read by software before a human ever sees them. This is how that works and how
to make sure a genuinely-qualified resume survives it. The goal is to make **real fit legible to a
parser and a busy recruiter** — not to trick anyone.

## How screening actually works

1. **Parsing.** An Applicant Tracking System (ATS — e.g. Workday, Greenhouse, Lever, Taleo, iCIMS)
   reads your file and tries to extract structured fields: name, contact, work history (company /
   title / dates), education, skills. Messy layouts make it extract garbage.
2. **Matching / ranking.** Recruiters search and filter by keywords, and increasingly an AI model
   scores how well your resume matches the job description. Both reward clear, relevant, keyword-aligned
   content.
3. **Human review.** Whatever passes reaches a person who spends ~10–30 seconds on the first pass.
   The top third of page one decides whether they keep reading.

So a resume has to win three times: parse cleanly, match the keywords, and read well fast.

## Formatting rules that keep parsers happy

The `tools/build.py` exporter produces a `.docx` that follows all of these — but if you edit by hand,
keep to them:

**Do**
- **Single column, top-to-bottom.** Parsers read in one flow. Two-column layouts get interleaved.
- **Standard section headings:** `Summary`, `Skills`, `Experience` (or `Work Experience`),
  `Education`, `Certifications`, `Projects`. Parsers look for these exact-ish words.
- **Standard fonts** (Calibri, Arial, Helvetica, Georgia, Times) at 10–12pt.
- **Simple bullets** (`•`) and plain text. Bold for emphasis is fine.
- **Clear dates** in a consistent format (`Jan 2022 – Mar 2024`, or `2022 – Present`).
- **Real text**, not images. The exported PDF has selectable text (an ATS can read it).
- **.docx when the application allows it** — it's the most reliably parsed format.

**Don't**
- No **tables, columns, or text boxes** for content — parsers drop or scramble them.
- No **images, icons, logos, charts, or headshots**.
- No putting name/contact in the **header/footer** region — many parsers ignore it entirely.
- No **graphics-based skill bars** ("★★★☆☆") — unparseable and meaningless to a screener.
- No **fancy/decorative fonts** or unusual section names ("Where I've Made Magic").
- No **image-only PDFs** (a scanned or exported-as-picture resume is invisible to an ATS).

## Keyword strategy (truthful)

Keywords are how both the ATS search and the AI ranker find you. Use them honestly:

- **Mirror the job description's exact wording** for skills you genuinely have. If the posting says
  "CI/CD pipelines," use "CI/CD" (not just "build automation"). If it says "Postgres," don't only
  say "relational databases."
- **Match the job title framing** in your summary when it's honest — if you've done the work of a
  "Data Engineer" and that's the title posted, frame yourself that way.
- **Include acronyms *and* their expansion once:** "Applicant Tracking System (ATS)," "Amazon Web
  Services (AWS)" — screeners may search for either form.
- **Put the most important keywords high** — the summary and the top of your skills and most-recent
  role carry the most weight.
- **Weave keywords into real accomplishments,** not a stuffed list. "Owned the CI/CD pipeline
  (GitHub Actions), cutting release time from 2 days to 2 hours" beats a bare keyword dump.

## What never to do (it backfires)

- **Hidden text / white-on-white keyword stuffing.** ATS strip formatting and see it; recruiters
  consider it fraud and blacklist candidates.
- **Fake keywords / skills you don't have.** You'll match, get the screen, and fail the interview —
  or get caught by a skills question in the first five minutes.
- **Inflated titles or dates.** Background checks and reference calls surface these.

We compete on *real* fit, surfaced well. That's both the ethical choice and the one that actually
leads to offers.

## Length & focus

- **1 page** for early-career; **1–2 pages** for experienced; rarely more than 2.
- **Tailor, don't dump.** A focused resume that clearly matches this job beats a comprehensive one
  that matches nothing in particular. That's the whole point of the master-profile approach — the
  full history lives there; each resume shows only the relevant slice.
- **Lead with impact.** Reorder bullets and roles so the most job-relevant, highest-impact items are
  what a 10-second skim lands on.
