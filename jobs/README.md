# Job descriptions

Save a posting here as a `.md` or `.txt` file, one file per job, named however you like
(`stripe-staff-backend.md`, `acme.txt`). Then point the tailoring script at it:

```bash
make tailor JOB=jobs/stripe-staff-backend.md
```

That writes `applications/<company>-<role>/` with a resume and a cover letter tailored to that one
posting, after a review that asks you about anything the posting wants that your profile doesn't
show yet.

Copy the posting in as plain text. The title and company on the first line help, and the
requirements matter far more than the benefits section:

```markdown
# Staff Backend Engineer, Stripe

**What you'll do**
- ...

**What we're looking for**
- ...
```

**Your postings here are gitignored**: only this README is tracked.
