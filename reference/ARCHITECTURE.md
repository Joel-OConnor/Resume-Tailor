# Architecture

Resume-Tailor has two halves that never mix: **deterministic Python** that you can trust and test,
and a **language model** that writes. Everything the model produces is checked by the
deterministic half before it reaches a file.

```mermaid
flowchart TB
    raw["my-documents/career-history/<br/>old resumes, LinkedIn export, answers.md"]
    jd["a job posting<br/>my-documents/job-postings/ or any path"]
    yaml[("output/master-profile.yaml<br/><i>the single source of truth</i>")]

    subgraph profile ["make profile"]
        draft["agent.build_profile<br/>draft"]
        refine["agent.refine_profile<br/>one record per fact, nothing irrelevant"]
        audit["review.review_profile<br/>audit + open questions"]
    end

    subgraph runs ["make resume · make tailor JOB=…"]
        write["agent.write_general<br/>or agent.tailor"]
        review["review: fixes, then agent.edit_documents"]
        ask{{"questions for the candidate"}}
        update["agent.update_profile<br/>then a revision"]
        export["render: .docx + .pdf"]
    end

    subgraph checks ["Deterministic checks, fully tested"]
        loader["profile.loader<br/>schema + semantics"]
        changes["verify.changes<br/>refine adds and loses nothing;<br/>updates add only what was said"]
        verify["verify.verify_resume<br/>every claim traces to the profile"]
        formats["documents.parser + review.check_linkedin<br/>format contracts"]
    end

    raw --> draft --> refine --> audit --> yaml
    yaml --> write
    jd --> write
    write --> review --> ask --> update --> export
    ask -- "no answers" --> export
    update --> yaml
    export --> out["output/general/ · output/applications/&lt;company&gt;-&lt;role&gt;/"]

    draft -.-> loader
    refine -.-> changes
    update -.-> changes
    write -.-> verify
    review -.-> verify
    write -.-> formats
```

## The rule that shapes everything

**The model never writes directly to a file.** Every model operation hands the retry loop in
`agent/loop.py` a check, and a reply is used only once the check passes:

| Operation | Must pass |
|---|---|
| `build_profile` (draft) | the profile loader |
| `refine_profile` | the loader, and `verify.changes.check_refinement`: nothing the draft lacks is added, nothing it has is lost, no level or years raised |
| `update_profile` (answers) | the loader, and `verify.changes.check_update`: every new employer, title, date, credential, technology, link or figure appears in the candidate's own answers |
| `write_general`, `tailor`, `edit_documents` | the format contract of every document, and `verify.verify_resume` on every document: the resume, the cover letter and the LinkedIn profile |

A failure sends the *specific* problems back to the model and retries. After the last attempt it
raises (`FabricationError` for an unsupported claim) rather than writing an unchecked document.
That is why "never fabricates" is a property of the system and not a hope about the prompt.

## The review between a draft and its export

`service/applications.py` runs the same review for both generating scripts: mechanical fixes
(`review.apply_fixes`), an editor pass (`agent.edit_documents`, held to the same checks), then
the questions only the candidate can answer. Answers are logged to
`my-documents/career-history/answers.md` and recorded in the profile by `agent.update_profile`;
the documents are revised against the updated profile, re-verified, and only then exported.
Questions reach the candidate through an `ask` callback, so the same run works at a terminal (the
CLI asks), in a test (a stub answers), or with no one there (the questions come back unasked).

## Why the model sits behind a Protocol

`llm.LanguageModel` is a `Protocol` with one method. Nothing in `agent/` or `service/` imports the
Anthropic SDK, so every test above the boundary drives a fake and stays deterministic, which is how
a package that calls an LLM still holds 100% branch coverage. A second provider is a new file, not
a refactor.

## What runs without an API key

Validating and auditing the profile (`resume-tailor profile validate`), rendering its Markdown view
and schema, and rendering a hand-edited `.md` to `.docx` and `.pdf` (`resume-tailor build`).
Everything that writes (the profile build, the general resume, a tailored application) needs one.
