"""The model operations, and the checks they are not allowed to skip.

Every test here drives a fake model: nothing in this file reaches a network. The cases are named
after the ways a language model actually fails this job: a resume that will not parse, a metric it
made up, a LinkedIn headline LinkedIn would cut off, a refined profile that quietly lost a figure,
an answer that ran out of tokens halfway down page one.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor.agent import (
    COVER_LETTER,
    LINKEDIN,
    RESUME,
    EditResult,
    GeneralResult,
    TailorResult,
    Usage,
    build_profile,
    edit_documents,
    prompts,
    refine_profile,
    tailor,
    update_profile,
    write_general,
)
from resume_tailor.agent.loop import one_line, questions, unfence
from resume_tailor.agent.writing import check_documents
from resume_tailor.errors import FabricationError, ModelError, ProfileError
from resume_tailor.llm import LanguageModel, Reply
from resume_tailor.profile import load_mapping, loads
from resume_tailor.review import Answer, Question
from resume_tailor.verify import format_violations, verify_resume

if TYPE_CHECKING:
    from collections.abc import Sequence

    from resume_tailor.profile.models import Profile

_INPUT_TOKENS = 11
_OUTPUT_TOKENS = 7


class FakeModel:
    """A :class:`~resume_tailor.llm.LanguageModel` that answers from a script.

    A plain string becomes a :class:`Reply` with fixed token counts, so a test can assert on
    accumulated usage; pass a ``Reply`` directly to control ``stop_reason``.
    """

    def __init__(self, replies: Sequence[str | Reply]) -> None:
        self.pending = list(replies)
        self.systems: list[str] = []
        self.prompts: list[str] = []

    def complete(self, system: str, prompt: str) -> Reply:
        """Return the next scripted reply, recording what it was asked."""
        self.systems.append(system)
        self.prompts.append(prompt)
        assert self.pending, "the model was called more times than the test scripted"
        reply = self.pending.pop(0)
        if isinstance(reply, Reply):
            return reply
        return Reply(reply, input_tokens=_INPUT_TOKENS, output_tokens=_OUTPUT_TOKENS)


# --- the world these tests run in -----------------------------------------------------------------
_PROFILE_DATA: dict[str, Any] = {
    "contact": {
        "name": "Ada Lovelace",
        "headline": "Principal Engineer",
        "email": "ada@example.com",
        "location": "London, UK",
    },
    "summary": "Engineer who writes programs for engines that do not exist yet.",
    "technologies": [
        {
            "group": "Languages",
            "items": [
                {"name": "Python", "level": "expert", "years": 8, "used_at": ["analytical"]},
                {"name": "Rust", "level": "exposure", "used_at": ["analytical"]},
            ],
        }
    ],
    "experience": [
        {
            "id": "analytical",
            "company": "Analytical Engine Programme",
            "location": "London, UK",
            "roles": [
                {
                    "title": "Principal Engineer",
                    "start": "2021-01",
                    "end": "present",
                    "highlights": [
                        {
                            "label": "Scheduler",
                            "text": "Cut batch runtime 38% by rewriting the scheduler in Python.",
                            "tags": ["Python", "performance"],
                        }
                    ],
                }
            ],
        }
    ],
    "notes": ["Confirm whether the punched-card work is worth listing."],
}

POSTING = """\
Difference Engine Ltd is hiring a Staff Engineer.

Requirements:
- 5+ years of Python
- Experience with Kubernetes
"""

RESUME_MD = """\
# Ada Lovelace
Staff Engineer
ada@example.com | London, UK

## Summary
Engineer who writes programs for engines that do not exist yet.

## Skills
**Languages:** Python

## Experience

### **Principal Engineer** – Analytical Engine Programme
January 2021 – Present | London, UK
- **Scheduler:** Cut batch runtime 38% by rewriting the scheduler in Python.
"""

LETTER = "# Ada Lovelace\nada@example.com\n\nDear Hiring Manager,\n\nSincerely,\\\nAda"

LINKEDIN_MD = """\
# Ada Lovelace

## Headline
Principal Engineer | Python, schedulers and engines that do not exist yet

## About
I write programs for engines that do not exist yet.

Most recently I cut batch runtime 38% by rewriting a scheduler in Python.

## Top Skills
**Top Skills:** Python

## Experience
### **Principal Engineer** – Analytical Engine Programme
January 2021 – Present | London, UK
I lead the programming of the Analytical Engine.
- Cut batch runtime 38% by rewriting the scheduler in Python.
**Skills:** Python

## Skills
**Skills:** Python
"""

BAD_RESUME = "Ada Lovelace, Staff Engineer\n\nNo name heading, so nothing can render this.\n"
INVENTED_RESUME = RESUME_MD.replace("Cut batch runtime 38%", "Cut batch runtime 92%")


@pytest.fixture
def profile() -> Profile:
    """Return a small but complete master profile."""
    return load_mapping(_PROFILE_DATA)


def delimited(**sections: str) -> str:
    """Build a delimited answer from ``SECTION_NAME=body`` pairs, underscores for spaces."""
    return "\n".join(
        f"{prompts.marker(name.replace('_', ' '))}\n{body}" for name, body in sections.items()
    )


def tailored(
    resume: str = RESUME_MD,
    *,
    company: str = "Difference Engine Ltd",
    role: str = "Staff Engineer",
    letter: str = LETTER,
    asked: str = "- The posting asks for Kubernetes. Have you used it?",
) -> str:
    """Build a complete, well-formed tailoring answer."""
    return delimited(
        COMPANY=company,
        ROLE=role,
        FIT="Strong on Python; Kubernetes is the gap.",
        RESUME=resume,
        COVER_LETTER=letter,
        QUESTIONS=asked,
    )


def general(resume: str = RESUME_MD, linkedin: str = LINKEDIN_MD) -> str:
    """Build a complete, well-formed general answer."""
    return delimited(RESUME=resume, LINKEDIN=linkedin)


def test_the_fake_model_satisfies_the_real_protocol() -> None:
    """Every test below is worth only as much as this: the fake is the interface, not a copy."""
    assert isinstance(FakeModel([]), LanguageModel)


# --- the general resume and the LinkedIn profile --------------------------------------------------
def test_a_clean_general_answer_comes_back_as_both_documents(profile: Profile) -> None:
    model = FakeModel([general()])

    result = write_general(profile, model)

    assert isinstance(result, GeneralResult)
    assert result.resume == RESUME_MD.strip()
    assert result.linkedin == LINKEDIN_MD.strip()
    assert result.usage == Usage(_INPUT_TOKENS, _OUTPUT_TOKENS, 1)
    assert model.systems == [prompts.GENERAL_SYSTEM]


def test_a_linkedin_profile_over_linkedin_s_limits_is_sent_back(profile: Profile) -> None:
    long_headline = LINKEDIN_MD.replace(
        "Principal Engineer | Python", "Principal Engineer | " + "Python " * 40
    )
    model = FakeModel([general(linkedin=long_headline), general()])

    result = write_general(profile, model)

    assert result.usage.attempts == 2
    assert "breaks LinkedIn's format" in model.prompts[1]
    assert "LinkedIn stops at 220" in model.prompts[1]


def test_an_invented_figure_on_linkedin_is_a_fabrication_like_any_other(profile: Profile) -> None:
    """The LinkedIn profile is checked by the same verifier as the resume."""
    invented = LINKEDIN_MD.replace("cut batch runtime 38%", "cut batch runtime 60%")
    model = FakeModel([general(linkedin=invented)] * 2)

    with pytest.raises(FabricationError, match="60%"):
        write_general(profile, model, max_attempts=2)


def test_a_general_answer_missing_the_linkedin_section_is_retried(profile: Profile) -> None:
    model = FakeModel([delimited(RESUME=RESUME_MD), general()])

    write_general(profile, model)

    assert "left them empty: LINKEDIN" in model.prompts[1]


def test_every_failing_document_is_reported_in_one_retry(profile: Profile) -> None:
    """One attempt should be able to fix both, so both are named at once."""
    model = FakeModel([general(resume=BAD_RESUME, linkedin="# Ada\n\n## About\nHi."), general()])

    write_general(profile, model)

    retry = model.prompts[1]
    assert "The resume does not follow the format contract" in retry
    assert "the ## Headline section is missing" in retry


# --- tailoring ------------------------------------------------------------------------------------
def test_a_clean_tailoring_answer_comes_back_whole(profile: Profile) -> None:
    """The happy path runs the real verifier: this resume claims nothing outside the profile."""
    model = FakeModel([tailored()])

    result = tailor(POSTING, profile, model)

    assert isinstance(result, TailorResult)
    assert result.resume == RESUME_MD.strip()
    assert result.cover_letter.startswith("# Ada Lovelace")
    assert result.company == "Difference Engine Ltd"
    assert result.role == "Staff Engineer"
    assert result.fit == "Strong on Python; Kubernetes is the gap."
    assert result.questions == ("The posting asks for Kubernetes. Have you used it?",)
    assert result.usage == Usage(_INPUT_TOKENS, _OUTPUT_TOKENS, 1)


def test_the_company_and_role_are_read_as_one_line_each(profile: Profile) -> None:
    model = FakeModel([tailored(company="**Difference Engine Ltd**\nfounded 1822", role="# Staff")])

    result = tailor(POSTING, profile, model)

    assert (result.company, result.role) == ("Difference Engine Ltd", "Staff")


def test_none_means_no_questions(profile: Profile) -> None:
    assert tailor(POSTING, profile, FakeModel([tailored(asked="- None.")])).questions == ()


def test_a_resume_that_breaks_the_format_contract_is_retried_with_the_parse_error(
    profile: Profile,
) -> None:
    model = FakeModel([tailored(BAD_RESUME), tailored()])

    result = tailor(POSTING, profile, model)

    assert result.usage.attempts == 2
    assert "The resume does not follow the format contract" in model.prompts[1]
    assert "'# Name' line" in model.prompts[1]


def test_a_cover_letter_that_will_not_render_is_retried_too(profile: Profile) -> None:
    model = FakeModel([tailored(letter="Dear Hiring Manager,\n\nSincerely,\nAda"), tailored()])

    tailor(POSTING, profile, model)

    assert "The cover letter does not follow the format contract" in model.prompts[1]


def test_an_invented_metric_is_retried_with_the_verifier_s_own_violations(
    profile: Profile,
) -> None:
    """A figure the profile cannot support is the failure this whole project exists to catch."""
    model = FakeModel([tailored(INVENTED_RESUME), tailored()])

    tailor(POSTING, profile, model)

    violations = format_violations(verify_resume(INVENTED_RESUME.strip(), profile))
    assert "92%" in violations, "the fixture only means anything while the verifier catches this"
    assert violations in model.prompts[1], "the retry carries the verifier's own words, verbatim"
    assert POSTING.strip() in model.prompts[1], "and the original request, unchanged"


def test_a_cover_letter_with_an_invented_figure_is_caught_too(profile: Profile) -> None:
    """A letter is checked by the same verifier: an invented number there is still invented."""
    letter = LETTER.replace("Dear Hiring Manager,", "Dear Hiring Manager, I cut costs 70%.")
    model = FakeModel([tailored(letter=letter)] * 3)

    with pytest.raises(FabricationError, match="The cover letter claims what the profile"):
        tailor(POSTING, profile, model)


def test_a_resume_that_keeps_inventing_raises_instead_of_being_written(profile: Profile) -> None:
    model = FakeModel([tailored(INVENTED_RESUME)] * 3)

    with pytest.raises(FabricationError) as caught:
        tailor(POSTING, profile, model)

    assert "92%" in str(caught.value), "the last violations travel with the error"
    assert "3 attempts" in str(caught.value)
    assert not model.pending, "every attempt should have been used"


def test_an_answer_that_never_parses_is_a_model_error_not_a_fabrication(profile: Profile) -> None:
    """Only an unsupported claim is fabrication; a malformed answer is the model misbehaving."""
    model = FakeModel([tailored(BAD_RESUME)] * 2)

    with pytest.raises(ModelError) as caught:
        tailor(POSTING, profile, model, max_attempts=2)

    assert not isinstance(caught.value, FabricationError)
    assert "2 attempts" in str(caught.value)


def test_usage_sums_the_tokens_of_every_attempt(profile: Profile) -> None:
    model = FakeModel([tailored(BAD_RESUME), tailored(BAD_RESUME), tailored()])

    assert tailor(POSTING, profile, model).usage == Usage(3 * _INPUT_TOKENS, 3 * _OUTPUT_TOKENS, 3)


def test_a_truncated_reply_is_a_failure_not_a_short_resume(profile: Profile) -> None:
    """A cut-off answer parses and verifies fine — it is simply missing the rest of the career."""
    cut_off = Reply(tailored(), input_tokens=5, output_tokens=3, stop_reason="max_tokens")
    model = FakeModel([cut_off, tailored()])

    result = tailor(POSTING, profile, model)

    assert result.usage == Usage(5 + _INPUT_TOKENS, 3 + _OUTPUT_TOKENS, 2)
    assert "hit the length limit" in model.prompts[1]
    assert "cut the least relevant content" in model.prompts[1]


def test_a_truncated_reply_on_the_last_attempt_ends_the_run(profile: Profile) -> None:
    model = FakeModel([Reply(tailored(), stop_reason="max_tokens")])

    with pytest.raises(ModelError, match="after 1 attempt:"):
        tailor(POSTING, profile, model, max_attempts=1)


def test_a_missing_section_is_named_in_the_retry(profile: Profile) -> None:
    truncated = tailored().split(prompts.marker(COVER_LETTER))[0]
    model = FakeModel([truncated, tailored()])

    tailor(POSTING, profile, model)

    assert "COVER LETTER, QUESTIONS" in model.prompts[1]


def test_an_empty_section_counts_as_missing(profile: Profile) -> None:
    model = FakeModel([tailored(company="   "), tailored()])

    tailor(POSTING, profile, model)

    assert "missing these sections, or left them empty: COMPANY" in model.prompts[1]


def test_a_section_wrapped_in_a_code_fence_is_unwrapped(profile: Profile) -> None:
    model = FakeModel([tailored(f"```markdown\n{RESUME_MD.strip()}\n```")])

    assert tailor(POSTING, profile, model).resume == RESUME_MD.strip()


def test_prose_before_the_first_delimiter_is_discarded(profile: Profile) -> None:
    model = FakeModel([f"Certainly! Here is the application:\n\n{tailored()}"])

    assert tailor(POSTING, profile, model).company == "Difference Engine Ltd"


def test_every_retry_is_reported_with_the_reason(profile: Profile) -> None:
    """An attempt takes minutes: a silent retry looks exactly like a hang."""
    two_invented = INVENTED_RESUME.replace("by rewriting", "for 12 teams by rewriting")
    model = FakeModel([tailored(two_invented), tailored(BAD_RESUME), tailored()])
    said: list[str] = []

    tailor(POSTING, profile, model, progress=said.append)

    assert len(said) == 2
    assert said[0].startswith(
        "the tailored resume and cover letter did not pass its checks (2 problems, the first: "
        "line 15: '12 teams' does not appear anywhere in the profile"
    )
    assert said[0].endswith("…); trying again, 2 of 3")
    assert "does not follow the format contract" in said[1]
    assert said[1].endswith("trying again, 3 of 3")


def test_a_long_reason_is_cut_to_one_readable_line(profile: Profile) -> None:
    model = FakeModel([delimited(RESUME=RESUME_MD), general()])
    said: list[str] = []

    write_general(profile, model, progress=said.append)

    assert said == [
        (
            "the general resume and LinkedIn profile did not pass its checks (The answer is "
            "missing these sections, or left them empty: LINKEDIN. Return all 2 sections…); "
            "trying again, 2 of 3"
        )
    ]


def test_max_attempts_below_one_is_a_programming_error(profile: Profile) -> None:
    model = FakeModel([])

    with pytest.raises(ValueError, match="max_attempts must be at least 1, got 0"):
        tailor(POSTING, profile, model, max_attempts=0)

    assert not model.systems, "a model that is never asked costs nothing"


# --- the editor -----------------------------------------------------------------------------------
EDITED = RESUME_MD.replace(
    "Cut batch runtime 38% by rewriting the scheduler in Python.",
    "Rewrote the scheduler in Python, cutting batch runtime 38%.",
)


def edited(resume: str = EDITED, *, letter: str = LETTER, asked: str = "- none") -> str:
    return delimited(RESUME=resume, COVER_LETTER=letter, QUESTIONS=asked)


def _edit(model: FakeModel, profile: Profile, **options: Any) -> EditResult:
    return edit_documents({RESUME: RESUME_MD, COVER_LETTER: LETTER}, profile, model, **options)


def test_the_editor_returns_every_document_and_its_questions(profile: Profile) -> None:
    model = FakeModel([edited(asked="- How large was the batch?\n* Which year did it ship?")])

    result = _edit(model, profile, flagged="- line 5: tense: bullets switch tense")

    assert result.documents == {RESUME: EDITED.strip(), COVER_LETTER: LETTER}
    assert result.questions == ("How large was the batch?", "Which year did it ship?")
    assert result.usage == Usage(_INPUT_TOKENS, _OUTPUT_TOKENS, 1)
    assert model.systems == [prompts.EDIT_SYSTEM]
    assert "- line 5: tense: bullets switch tense" in model.prompts[0]


def test_the_editor_is_told_when_nothing_was_flagged(profile: Profile) -> None:
    model = FakeModel([edited()])

    assert _edit(model, profile).questions == ()
    assert "Nothing was flagged." in model.prompts[0]


def test_an_edit_that_changes_an_entry_is_sent_back(profile: Profile) -> None:
    renamed = EDITED.replace("**Principal Engineer** –", "**Engineer** –")
    model = FakeModel([edited(renamed), edited()])

    result = _edit(model, profile)

    assert result.usage.attempts == 2
    assert "Keep every role and degree heading" in model.prompts[1]


def test_an_edit_that_changes_a_figure_is_refused(profile: Profile) -> None:
    with pytest.raises(FabricationError, match="39%"):
        _edit(FakeModel([edited(EDITED.replace("38%", "39%"))] * 3), profile)


def test_an_edit_needs_its_questions_section(profile: Profile) -> None:
    model = FakeModel([delimited(RESUME=EDITED, COVER_LETTER=LETTER)] * 3)

    with pytest.raises(ModelError, match="QUESTIONS"):
        _edit(model, profile)


def test_an_edit_that_does_not_parse_is_retried(profile: Profile) -> None:
    model = FakeModel([edited("no name line here"), edited()])

    assert _edit(model, profile).usage.attempts == 2
    assert "format contract" in model.prompts[1]


def test_a_revision_works_answers_in_and_asks_nothing(profile: Profile) -> None:
    """After the review there is no second round of questions, and entries may grow."""
    answers = (Answer(Question("How large was the batch?"), "About 40 jobs a night."),)
    added_role = EDITED + "\n### **Engineer** – Analytical Engine Programme\n2021 – Present\n"
    model = FakeModel([delimited(RESUME=added_role, COVER_LETTER=LETTER)])

    result = _edit(model, profile, answers=answers)

    assert result.questions == ()
    assert "### **Engineer**" in result.documents[RESUME]
    prompt = model.prompts[0]
    assert "Q: How large was the batch?\nA: About 40 jobs a night." in prompt
    assert prompts.marker(prompts.QUESTIONS) not in prompt
    assert "<mechanical-review>" not in prompt


def test_check_documents_passes_clean_documents(profile: Profile) -> None:
    documents = {RESUME: RESUME_MD, COVER_LETTER: LETTER, LINKEDIN: LINKEDIN_MD}
    assert check_documents(documents, profile) is None


# --- the master profile ---------------------------------------------------------------------------
PROFILE_YAML = textwrap.dedent("""\
    schema_version: 1
    contact:
      name: Ada Lovelace
      headline: Principal Engineer
      email: ada@example.com
    summary: Engineer who writes programs for engines that do not exist yet.
    technologies:
      - group: Languages
        items:
          - name: Python
            level: expert
            years: 8
            used_at: [analytical]
          - name: Scheduler rewrite
    experience:
      - id: analytical
        company: Analytical Engine Programme
        roles:
          - title: Principal Engineer
            start: "2021-01"
            end: present
            highlights:
              - label: Scheduler
                text: Cut batch runtime 38% by rewriting the scheduler in Python.
              - text: Rewrote the scheduler in Python, cutting batch runtime 38%.
""")

REFINED_YAML = PROFILE_YAML.replace("      - name: Scheduler rewrite\n", "").replace(
    "          - text: Rewrote the scheduler in Python, cutting batch runtime 38%.\n", ""
)

BAD_PROFILE_YAML = PROFILE_YAML.replace('"2021-01"', '"Jan 2021"')
DOCUMENTS = {"linkedin.txt": "Ada Lovelace, Principal Engineer. Cut batch runtime 38%."}


def refined(
    yaml_text: str = REFINED_YAML, changes: str = "- Merged the two scheduler highlights."
) -> str:
    return delimited(PROFILE=yaml_text, CHANGES=changes)


def test_build_profile_returns_yaml_the_loader_accepts() -> None:
    model = FakeModel([f"```yaml\n{PROFILE_YAML.strip()}\n```"])

    yaml_text, usage = build_profile(DOCUMENTS, model)

    assert yaml_text == PROFILE_YAML.strip(), "the fence is stripped, the YAML is not touched"
    assert loads(yaml_text).contact.name == "Ada Lovelace"
    assert usage == Usage(_INPUT_TOKENS, _OUTPUT_TOKENS, 1)


def test_invalid_yaml_is_retried_with_the_loader_s_own_message() -> None:
    """The loader's path (``experience[0].roles[0].start``) is what makes a retry actionable."""
    model = FakeModel([BAD_PROFILE_YAML, PROFILE_YAML])

    yaml_text, usage = build_profile(DOCUMENTS, model)

    assert yaml_text == PROFILE_YAML.strip()
    assert usage.attempts == 2
    assert "experience[0].roles[0].start: expected YYYY or YYYY-MM" in model.prompts[1]


def test_a_truncated_profile_is_told_to_compact_not_to_cut() -> None:
    """Cutting a resume loses a bullet; cutting the profile loses the career it came from."""
    model = FakeModel([Reply(PROFILE_YAML, stop_reason="max_tokens"), PROFILE_YAML])

    build_profile(DOCUMENTS, model)

    assert "Do not drop roles, highlights or technologies" in model.prompts[1]
    assert "cut the least relevant content" not in model.prompts[1]


def test_yaml_that_never_loads_raises_a_model_error() -> None:
    model = FakeModel(["not: [a, profile", "still: not: a profile"])

    with pytest.raises(ModelError, match="the master profile still failed its checks"):
        build_profile(DOCUMENTS, model, max_attempts=2)


def test_refining_returns_the_cleaner_profile_and_what_changed() -> None:
    model = FakeModel([refined()])

    edit = refine_profile(PROFILE_YAML, DOCUMENTS, model)

    assert edit.yaml == REFINED_YAML.strip()
    assert [item.name for item in edit.profile.technologies[0].items] == ["Python"]
    assert edit.changes == ("Merged the two scheduler highlights.",)
    assert edit.usage == Usage(_INPUT_TOKENS, _OUTPUT_TOKENS, 1)
    assert model.systems == [prompts.REFINE_PROFILE_SYSTEM]


def test_refining_shows_the_model_the_draft_its_sources_and_its_audit() -> None:
    model = FakeModel([refined()])

    refine_profile(PROFILE_YAML, DOCUMENTS, model)

    prompt = model.prompts[0]
    assert PROFILE_YAML.strip() in prompt
    assert '<document name="linkedin.txt">' in prompt
    assert "duplicate-highlight" not in prompt, "the audit carries messages, not rule names"
    assert "says what experience[0].roles[0].highlights[0] already says" in prompt


def test_a_refinement_that_adds_a_fact_is_sent_back_then_refused() -> None:
    """The draft is the ceiling: a refiner that 'finds' a new figure has invented one."""
    inflated = REFINED_YAML.replace("38%", "45%")
    model = FakeModel([refined(inflated), refined()])

    edit = refine_profile(PROFILE_YAML, DOCUMENTS, model)

    assert edit.usage.attempts == 2
    assert "introduced the figure '45%'" in model.prompts[1]
    with pytest.raises(FabricationError, match="45%"):
        refine_profile(PROFILE_YAML, DOCUMENTS, FakeModel([refined(inflated)] * 3))


def test_a_refinement_that_does_not_load_is_retried() -> None:
    model = FakeModel([refined(BAD_PROFILE_YAML), refined()])

    refine_profile(PROFILE_YAML, DOCUMENTS, model)

    assert "not a valid master profile" in model.prompts[1]


def test_a_refinement_without_its_change_log_is_retried() -> None:
    model = FakeModel([delimited(PROFILE=REFINED_YAML), refined()])

    refine_profile(PROFILE_YAML, DOCUMENTS, model)

    assert "left them empty: CHANGES" in model.prompts[1]


def test_refining_an_invalid_draft_fails_before_the_model_is_asked() -> None:
    model = FakeModel([])

    with pytest.raises(ProfileError):
        refine_profile(BAD_PROFILE_YAML, DOCUMENTS, model)
    assert not model.prompts


ANSWERS = (Answer(Question("How many jobs a night did it run?"), "About 40 jobs a night."),)
UPDATED_YAML = REFINED_YAML.replace(
    "by rewriting the scheduler in Python.",
    "by rewriting the scheduler in Python, which ran about 40 jobs a night.",
)


def test_an_update_records_what_the_answers_say() -> None:
    model = FakeModel([UPDATED_YAML])

    edit = update_profile(REFINED_YAML, ANSWERS, model)

    assert edit.yaml == UPDATED_YAML.strip()
    assert "40 jobs a night" in edit.profile.experience[0].roles[0].highlights[0].text
    assert model.systems == [prompts.UPDATE_PROFILE_SYSTEM]
    assert "Q: How many jobs a night did it run?\nA: About 40 jobs a night." in model.prompts[0]


def test_an_update_that_records_more_than_was_said_is_refused() -> None:
    inflated = UPDATED_YAML.replace("about 40 jobs", "about 400 jobs")
    model = FakeModel([inflated, UPDATED_YAML])

    edit = update_profile(REFINED_YAML, ANSWERS, model)

    assert edit.usage.attempts == 2
    assert "introduced the figure '400'" in model.prompts[1]


def test_an_update_that_does_not_load_is_retried() -> None:
    model = FakeModel([BAD_PROFILE_YAML, UPDATED_YAML])

    update_profile(REFINED_YAML, ANSWERS, model)

    assert "not a valid master profile" in model.prompts[1]


# --- reading replies ------------------------------------------------------------------------------
def test_reply_helpers() -> None:
    assert unfence("```yaml\na: 1\n```") == "a: 1"
    assert unfence("  plain  ") == "plain"
    assert one_line("## **Acme**\nmore") == "Acme"
    assert questions("- one\n* two\n• three\n\n- none") == ("one", "two", "three")


def test_usage_adds_up() -> None:
    assert Usage(1, 2, 1) + Usage(3, 4, 2) == Usage(4, 6, 3)


# --- what the model is told -----------------------------------------------------------------------
def test_the_general_prompt_carries_the_profile_and_both_formats(profile: Profile) -> None:
    prompt = prompts.general_prompt(profile)

    assert "Cut batch runtime 38%" in prompt, "the profile's own words are the source of fact"
    assert prompts.RESUME_FORMAT.strip() in prompt
    assert prompts.LINKEDIN_FORMAT.strip() in prompt
    for section in prompts.GENERAL_SECTIONS:
        assert prompts.marker(section) in prompt


def test_the_tailor_prompt_carries_the_posting_the_profile_and_the_contracts(
    profile: Profile,
) -> None:
    prompt = prompts.tailor_prompt(POSTING, profile)

    assert POSTING.strip() in prompt
    assert "Confirm whether the punched-card work" in prompt, "notes are shown, marked unconfirmed"
    assert prompts.COVER_LETTER_FORMAT.strip() in prompt
    assert "Kubernetes" in prompt, "the mechanical gap analysis rides along"
    for section in prompts.TAILOR_SECTIONS:
        assert prompts.marker(section) in prompt


def test_the_system_prompts_state_the_rules_the_checks_enforce() -> None:
    """The checks catch fabrication; the prompts are what keep them from having to."""
    for system in (prompts.GENERAL_SYSTEM, prompts.TAILOR_SYSTEM):
        assert "NEVER FABRICATE" in system
        assert "UNCONFIRMED" in system
        assert '"exposure" or "working"' in system
    assert "220 characters" in prompts.GENERAL_SYSTEM
    assert "Add anything" in prompts.REFINE_PROFILE_SYSTEM
    assert "Lose anything" in prompts.REFINE_PROFILE_SYSTEM
    assert "the answers themselves do not state" in prompts.UPDATE_PROFILE_SYSTEM
    assert "Bold the job title" in prompts.RESUME_FORMAT
    assert "no\n  level recorded may be listed only where the profile shows it in real use" in (
        prompts.TAILOR_SYSTEM
    )
    assert '"core", "daily" or "main stack" is proficient' in prompts.PROFILE_SYSTEM
    for system in (prompts.PROFILE_SYSTEM, prompts.REFINE_PROFILE_SYSTEM):
        assert "in the second person" in system
    assert "never\n  put a settled answer there" in prompts.UPDATE_PROFILE_SYSTEM


def test_the_profile_prompt_carries_the_schema_and_every_document() -> None:
    prompt = prompts.profile_prompt({"old-resume.txt": "Ada Lovelace", "linkedin.txt": "Engineer"})

    assert '"schema_version"' in prompt
    assert '<document name="old-resume.txt">' in prompt
    assert '<document name="linkedin.txt">' in prompt


def test_the_refine_prompt_says_when_the_audit_found_nothing() -> None:
    assert "The audit found nothing." in prompts.refine_profile_prompt("a: 1", {}, "")


def test_the_retry_prompt_leads_with_the_problems_and_keeps_the_request() -> None:
    retry = prompts.retry_prompt("ORIGINAL REQUEST", "- you invented a metric")

    assert retry.index("- you invented a metric") < retry.index("ORIGINAL REQUEST")
    assert "rejected by an automatic check" in retry
