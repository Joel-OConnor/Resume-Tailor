# My documents

Everything you bring goes here. The folder is gitignored (only the READMEs are tracked), so none
of it is ever committed.

- [`career-history/`](career-history/): anything about your career, such as old resumes, a
  LinkedIn PDF export, brag docs and notes. `make profile` reads it all and builds
  `output/master-profile.yaml` from it.
- [`job-postings/`](job-postings/): one `.md` or `.txt` file per job you want to apply to.
  `make tailor JOB=<file name>` writes a resume and cover letter for it.

Everything the project writes lands in [`output/`](../output/).
