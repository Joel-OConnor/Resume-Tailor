# How to build your master profile

Your master profile (`output/master-profile.yaml`) is the foundation: the better it is, the better
every resume, LinkedIn profile and cover letter drawn from it. It should hold every real fact about
your career, once, because every document can only *select* from what's here.

It's structured YAML rather than prose on purpose: Claude can then pick roles by date, find the
highlights tagged with a skill a posting asks for, and check the posting's exact wording against
your technology aliases, instead of re-reading paragraphs and guessing.

## The fastest path

1. Drop whatever you have into
   [`my-documents/career-history/`](../my-documents/career-history/) (see
   [its README](../my-documents/career-history/README.md) for ideas). Old resumes (PDF, Word or
   text) and a LinkedIn export alone are a great start.
2. Build it:

   ```bash
   make profile
   ```

   It names every file it read, and every file it could **not** read: a scanned PDF has no text
   in it, so add a text or Word version of that one instead. Then it works in three passes:

   - **Draft:** every distinct fact from your documents, recorded as YAML.
   - **Refine:** a second read that records each fact once and in the right place. The same
     accomplishment told by two documents becomes one highlight (keeping every number), each
     highlight moves under the role whose dates it fits, accomplishments filed as skills and
     other noise are dropped, and no level or years claim more than your documents show. It is
     checked mechanically: refining can merge and tidy, but it can never add a fact or lose one.
   - **Settle:** anything the documents left unclear (two different figures, a missing month) was
     put in `notes`. Those come back as questions, asked right there. Answer in a sentence, or
     press Enter to skip; answers go straight into the profile and into
     `my-documents/career-history/answers.md`.

   It will not overwrite a profile you already have; `make profile FORCE=--force` replaces one,
   keeping a timestamped backup in `output/backups/`.

3. Read it over:

   ```bash
   .venv/bin/resume-tailor profile render      # writes output/master-profile.md to proofread
   .venv/bin/resume-tailor profile validate    # checks it, and lists what still needs a look
   ```

4. Correct anything wrong, and add accomplishments the old resumes left out.

Starting by hand instead? Copy the [worked example](../examples/master-profile.yaml):

```bash
cp examples/master-profile.yaml output/master-profile.yaml
```

## The shape of the file

```yaml
contact:        # name, headline, email, phone, location, links
target_roles:   # the titles you're aiming at; tells tailoring what to emphasise
summary:        # a generic professional summary; each resume gets a targeted rewrite
technologies:   # every tool, grouped, with aliases / level / years / where you used it
experience:     # every employer, with each title you held there as a separate role
education:      # degrees and programs
certifications: awards: projects:
notes:          # open questions, never printed on a resume
```

Two fields do most of the work at tailoring time:

- **`technologies[].aliases`**: the other spellings a screener might search for. `K8s` for
  Kubernetes, `Postgres` for PostgreSQL, `AWS` for Amazon Web Services. A posting can say either;
  listing both means the match is found and the resume prints whichever wording the posting used.
- **`highlights[].tags`**: the keywords a given accomplishment is *evidence for*. When a posting
  demands "high availability," tags are how the right bullet surfaces instead of the newest one.

Your editor can validate as you type. The file already points at the schema:

```yaml
# yaml-language-server: $schema=../schema/master-profile.schema.json
```

## What makes a profile strong

- **Capture more than one resume's worth.** List *every* role, project, tool, and win. A single
  resume shows ~30–40% of this; tailoring needs the other 60% to draw from for different jobs.
- **Quantify everything you can.** Numbers are what make bullets land and what screeners latch onto:
  percentages, dollars, time saved, users, scale, team size, revenue. "Improved performance" → "cut
  API p95 latency 42% (1.2s → 700ms), saving ~$18k/mo in compute."
- **Use strong, specific verbs.** Led, built, shipped, migrated, automated, negotiated, reduced,
  grew, designed. Avoid "responsible for" and "helped with."
- **Give each highlight a `label`.** It becomes the bold lead-in on the resume
  (`**Data Layer Design:** Designed normalized schemas…`), which is what a ten-second skim reads.
- **Fill in `scope`.** Team size, org, budget, traffic: the context a bullet can't carry but an
  interviewer will ask about.
- **Keep it truthful.** Everything here should be defensible in an interview. If you're unsure a
  number is right, put it in `notes` and fix it later: `resume-tailor profile validate` will keep
  reminding you, and nothing in `notes` is ever printed.

## Keeping it fresh

Update the profile whenever you finish a project or hit a milestone: it's much easier to capture a
win the week it happens than to reconstruct it a year later at 11pm before an application. Run
`resume-tailor profile validate` after editing; it catches typos, bad dates, technologies pointing
at employers that don't exist, and anything recorded twice. The questions `make resume` and
`make tailor` ask during their review also land here, so the profile gets better every time you
use it.
