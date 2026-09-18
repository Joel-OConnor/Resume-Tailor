# How to build your master profile

Your master profile (`profile/master-profile.yaml`) is the foundation — the better it is, the better
every tailored resume. It should hold **everything**, because tailoring can only *select* from
what's here.

It's structured YAML rather than prose on purpose: Claude can then pick roles by date, find the
highlights tagged with a skill a posting asks for, and check the posting's exact wording against
your technology aliases — instead of re-reading paragraphs and guessing.

## The fastest path

1. Drop whatever you have into [`raw/`](raw/) — see [raw/README.md](raw/README.md) for ideas. Old
   resumes (PDF, Word or text) and a LinkedIn export alone are a great start.
2. Build it:

   ```bash
   make profile
   ```

   It names every file it read, and every file it could **not** read — a scanned PDF has no text
   in it, so add a text or Word version of that one instead. It will not overwrite a profile you
   already have; `make profile FORCE=--force` replaces one, keeping a timestamped backup beside it.

   In Claude Code you can instead say: **"Build my master profile from the files in profile/raw."**
   Claude reads everything, writes `master-profile.yaml`, and asks about anything unclear.
3. Check it and read it over:

   ```bash
   make profile-check     # validates, and prints anything still unconfirmed
   make profile-md        # renders profile/MASTER_PROFILE.md to proofread
   ```

4. Correct anything wrong, and add accomplishments the old resumes left out.

Starting by hand instead? Copy the worked example:

```bash
cp templates/master-profile.example.yaml profile/master-profile.yaml
```

## The shape of the file

```yaml
contact:        # name, headline, email, phone, location, links
target_roles:   # the titles you're aiming at — tells tailoring what to emphasise
summary:        # a generic professional summary; each resume gets a targeted rewrite
technologies:   # every tool, grouped, with aliases / level / years / where you used it
experience:     # every employer, with each title you held there as a separate role
education:      # degrees and programs
certifications: awards: projects:
notes:          # open questions — never printed on a resume
```

Two fields do most of the work at tailoring time:

- **`technologies[].aliases`** — the other spellings a screener might search for. `K8s` for
  Kubernetes, `Postgres` for PostgreSQL, `AWS` for Amazon Web Services. A posting can say either;
  listing both means the match is found and the resume prints whichever wording the posting used.
- **`highlights[].tags`** — the keywords a given accomplishment is *evidence for*. When a posting
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
- **Fill in `scope`.** Team size, org, budget, traffic — the context a bullet can't carry but an
  interviewer will ask about.
- **Keep it truthful.** Everything here should be defensible in an interview. If you're unsure a
  number is right, put it in `notes` and fix it later — `make profile-check` will keep reminding
  you, and Claude will raise it rather than print it.

## Keeping it fresh

Update the profile whenever you finish a project or hit a milestone — it's much easier to capture a
win the week it happens than to reconstruct it a year later at 11pm before an application. Run
`make profile-check` after editing; it catches typos, bad dates, and technologies pointing at
employers that don't exist.
