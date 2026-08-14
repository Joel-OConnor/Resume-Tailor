"""The retry loop, and the checks it is not allowed to skip.

Every test here drives a fake model: nothing in this file reaches a network. The cases are named
after the ways a language model actually fails this job — a resume that will not parse, a metric it
made up, an answer that ran out of tokens halfway down page one.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor.agent import TailorResult, Usage, build_profile, prompts, tailor
from resume_tailor.errors import FabricationError, ModelError
from resume_tailor.llm import LanguageModel, Reply
from resume_tailor.profile import load_mapping, loads
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

RESUME = """\
# Ada Lovelace
Staff Engineer
ada@example.com | London, UK

## Summary
Engineer who writes programs for engines that do not exist yet.

## Skills
**Languages:** Python

## Experience

### Analytical Engine Programme — Principal Engineer
London, UK | January 2021 – Present
- **Scheduler:** Cut batch runtime 38% by rewriting the scheduler in Python.
"""

BAD_RESUME = "Ada Lovelace, Staff Engineer\n\nNo name heading, so nothing can render this.\n"

INVENTED_RESUME = RESUME.replace("Cut batch runtime 38%", "Cut batch runtime 92%")

PROFILE_YAML = textwrap.dedent("""\
    schema_version: 1
    contact:
      name: Ada Lovelace
      headline: Principal Engineer
      email: ada@example.com
    summary: Engineer who writes programs for engines that do not exist yet.
    experience:
      - id: analytical
        company: Analytical Engine Programme
        roles:
          - title: Principal Engineer
            start: "2021-01"
            end: present
""")

BAD_PROFILE_YAML = PROFILE_YAML.replace('"2021-01"', '"Jan 2021"')


@pytest.fixture
def profile() -> Profile:
    """Return a small but complete master profile."""
    return load_mapping(_PROFILE_DATA)


LETTER = "# Ada Lovelace\nada@example.com\n\nDear Hiring Manager,\n\nSincerely,\nAda"


def answer(
    resume: str = RESUME,
    *,
    company: str = "Difference Engine Ltd",
    role: str = "Staff Engineer",
    letter: str = LETTER,
) -> str:
    """Build a complete, well-formed tailoring answer."""
    return "\n".join(
        (
            prompts.marker("COMPANY"),
            company,
            prompts.marker("ROLE"),
            role,
            prompts.marker("RESUME"),
            resume,
            prompts.marker("FIT REPORT"),
            "## Keyword coverage\n\nStrong on Python; Kubernetes is a gap.",
            prompts.marker("COVER LETTER"),
            letter,
            prompts.marker("LINKEDIN"),
            "**Headline:** Principal Engineer\n\n## About\n\nI write programs for engines.",
        )
    )


# --- tailoring ------------------------------------------------------------------------------------
def test_the_fake_model_satisfies_the_real_protocol() -> None:
    """Every test below is worth only as much as this: the fake is the interface, not a copy."""
    assert isinstance(FakeModel([]), LanguageModel)


def test_a_clean_answer_comes_back_as_four_documents(profile: Profile) -> None:
    """The happy path runs the real verifier: this resume claims nothing outside the profile."""
    model = FakeModel([answer()])

    result = tailor(POSTING, profile, model)

    assert isinstance(result, TailorResult)
    assert result.resume == RESUME.strip()
    assert result.company == "Difference Engine Ltd"
    assert result.role == "Staff Engineer"
    assert "Kubernetes is a gap" in result.fit_report
    assert result.cover_letter.startswith("# Ada Lovelace")
    assert "## About" in result.linkedin
    assert result.usage == Usage(_INPUT_TOKENS, _OUTPUT_TOKENS, 1)
    assert len(model.prompts) == 1


def test_the_company_and_role_are_read_as_one_line_each(profile: Profile) -> None:
    model = FakeModel([answer(company="**Difference Engine Ltd**\nfounded 1822", role="# Staff")])

    result = tailor(POSTING, profile, model)

    assert result.company == "Difference Engine Ltd"
    assert result.role == "Staff"


def test_a_resume_that_breaks_the_format_contract_is_retried_with_the_parse_error(
    profile: Profile,
) -> None:
    model = FakeModel([answer(BAD_RESUME), answer()])

    result = tailor(POSTING, profile, model)

    assert result.resume == RESUME.strip()
    assert result.usage.attempts == 2
    assert "does not follow the format contract" in model.prompts[1]
    assert "'# Name' line" in model.prompts[1]


def test_a_cover_letter_that_will_not_render_is_retried_too(profile: Profile) -> None:
    """It reaches the same renderer as the resume, so it fails here rather than at export."""
    model = FakeModel([answer(letter="Dear Hiring Manager,\n\nSincerely,\nAda"), answer()])

    tailor(POSTING, profile, model)

    assert "The cover letter does not follow the format contract" in model.prompts[1]


def test_an_invented_metric_is_retried_with_the_verifier_s_own_violations(
    profile: Profile,
) -> None:
    """A figure the profile cannot support is the failure this whole project exists to catch."""
    model = FakeModel([answer(INVENTED_RESUME), answer()])

    result = tailor(POSTING, profile, model)

    violations = format_violations(verify_resume(INVENTED_RESUME.strip(), profile))
    assert "92%" in violations, "the fixture only means anything while the verifier catches this"
    assert result.resume == RESUME.strip()
    assert violations in model.prompts[1], "the retry carries the verifier's own words, verbatim"
    assert POSTING.strip() in model.prompts[1], "and the original request, unchanged"


def test_a_resume_that_keeps_inventing_raises_instead_of_being_written(profile: Profile) -> None:
    model = FakeModel([answer(INVENTED_RESUME)] * 3)

    with pytest.raises(FabricationError) as caught:
        tailor(POSTING, profile, model)

    assert "92%" in str(caught.value), "the last violations travel with the error"
    assert "3 attempts" in str(caught.value)
    assert not model.pending, "every attempt should have been used"


def test_an_answer_that_never_parses_is_a_model_error_not_a_fabrication(profile: Profile) -> None:
    """Only an unsupported claim is fabrication; a malformed answer is the model misbehaving."""
    model = FakeModel([answer(BAD_RESUME)] * 2)

    with pytest.raises(ModelError) as caught:
        tailor(POSTING, profile, model, max_attempts=2)

    assert not isinstance(caught.value, FabricationError)
    assert "2 attempts" in str(caught.value)


def test_usage_sums_the_tokens_of_every_attempt(profile: Profile) -> None:
    model = FakeModel([answer(BAD_RESUME), answer(BAD_RESUME), answer()])

    usage = tailor(POSTING, profile, model).usage

    assert usage == Usage(3 * _INPUT_TOKENS, 3 * _OUTPUT_TOKENS, 3)


def test_a_truncated_reply_is_a_failure_not_a_short_resume(profile: Profile) -> None:
    """A cut-off answer parses and verifies fine — it is simply missing the rest of the career."""
    cut_off = Reply(answer(), input_tokens=5, output_tokens=3, stop_reason="max_tokens")
    model = FakeModel([cut_off, answer()])

    result = tailor(POSTING, profile, model)

    assert result.usage == Usage(5 + _INPUT_TOKENS, 3 + _OUTPUT_TOKENS, 2)
    assert "hit the length limit" in model.prompts[1]


def test_a_truncated_reply_on_the_last_attempt_ends_the_run(profile: Profile) -> None:
    cut_off = Reply(answer(), stop_reason="max_tokens")
    model = FakeModel([cut_off])

    with pytest.raises(ModelError, match="after 1 attempt:"):
        tailor(POSTING, profile, model, max_attempts=1)


def test_a_missing_section_is_named_in_the_retry(profile: Profile) -> None:
    truncated = answer().split(prompts.marker("COVER LETTER"))[0]
    model = FakeModel([truncated, answer()])

    tailor(POSTING, profile, model)

    assert "COVER LETTER, LINKEDIN" in model.prompts[1]


def test_an_empty_section_counts_as_missing(profile: Profile) -> None:
    model = FakeModel([answer(company="   "), answer()])

    tailor(POSTING, profile, model)

    assert "missing these sections, or left them empty: COMPANY" in model.prompts[1]


def test_a_section_wrapped_in_a_code_fence_is_unwrapped(profile: Profile) -> None:
    model = FakeModel([answer(f"```markdown\n{RESUME.strip()}\n```")])

    result = tailor(POSTING, profile, model)

    assert result.resume == RESUME.strip()


def test_prose_before_the_first_delimiter_is_discarded(profile: Profile) -> None:
    model = FakeModel([f"Certainly! Here is the application:\n\n{answer()}"])

    result = tailor(POSTING, profile, model)

    assert result.resume == RESUME.strip()
    assert result.linkedin.endswith("I write programs for engines.")


# --- building a profile ---------------------------------------------------------------------------
def test_build_profile_returns_yaml_the_loader_accepts() -> None:
    model = FakeModel([f"```yaml\n{PROFILE_YAML.strip()}\n```"])

    yaml_text, usage = build_profile({"resume-2019.txt": "Ada Lovelace, Principal Engineer"}, model)

    assert yaml_text == PROFILE_YAML.strip(), "the fence is stripped, the YAML is not touched"
    assert loads(yaml_text).contact.name == "Ada Lovelace"
    assert usage == Usage(_INPUT_TOKENS, _OUTPUT_TOKENS, 1)


def test_invalid_yaml_is_retried_with_the_loader_s_own_message() -> None:
    """The loader's path (``experience[0].roles[0].start``) is what makes a retry actionable."""
    model = FakeModel([BAD_PROFILE_YAML, PROFILE_YAML])

    yaml_text, usage = build_profile({"notes.md": "Ada worked on the engine."}, model)

    assert yaml_text == PROFILE_YAML.strip()
    assert usage.attempts == 2
    assert "not a valid master profile" in model.prompts[1]
    assert "experience[0].roles[0].start: expected YYYY or YYYY-MM" in model.prompts[1]
    assert "'Jan 2021'" in model.prompts[1]


def test_yaml_that_never_loads_raises_a_model_error() -> None:
    model = FakeModel(["not: [a, profile", "still: not: a profile"])

    with pytest.raises(ModelError, match="the master profile still failed its checks"):
        build_profile({"notes.md": "Ada worked on the engine."}, model, max_attempts=2)


# --- the loop itself ------------------------------------------------------------------------------
def test_max_attempts_below_one_is_a_programming_error(profile: Profile) -> None:
    model = FakeModel([])

    with pytest.raises(ValueError, match="max_attempts must be at least 1, got 0"):
        tailor(POSTING, profile, model, max_attempts=0)

    assert not model.systems, "a model that is never asked costs nothing"


# --- what the model is told -----------------------------------------------------------------------
def test_the_tailor_prompt_carries_the_posting_the_profile_and_the_format_contract(
    profile: Profile,
) -> None:
    prompt = prompts.tailor_prompt(POSTING, profile)

    assert POSTING.strip() in prompt
    assert "Cut batch runtime 38%" in prompt, "the profile's own words are the source of fact"
    assert "Confirm whether the punched-card work" in prompt, "notes are shown, marked unconfirmed"
    assert prompts.RESUME_FORMAT in prompt
    assert prompts.COVER_LETTER_FORMAT in prompt
    assert prompts.OUTPUT_CONTRACT in prompt
    assert "Kubernetes" in prompt, "the mechanical gap analysis rides along"
    for section in prompts.SECTIONS:
        assert prompts.marker(section) in prompt


def test_the_tailor_system_prompt_states_every_rule_the_checks_enforce() -> None:
    """The checks catch fabrication; the prompt is what keeps them from having to."""
    system = prompts.TAILOR_SYSTEM
    assert "NEVER FABRICATE" in system
    assert "UNCONFIRMED" in system
    assert '"exposure" or "working"' in system


def test_the_profile_prompt_carries_the_schema_and_every_document() -> None:
    prompt = prompts.profile_prompt({"old-resume.txt": "Ada Lovelace", "linkedin.txt": "Engineer"})

    assert "master-profile.schema.json" in prompt, "the schema is the contract, generated not typed"
    assert '"schema_version"' in prompt
    assert '<document name="old-resume.txt">' in prompt
    assert '<document name="linkedin.txt">' in prompt
    assert "Ada Lovelace" in prompt


def test_the_retry_prompt_leads_with_the_problems_and_keeps_the_request() -> None:
    retry = prompts.retry_prompt("ORIGINAL REQUEST", "- you invented a metric")

    assert retry.index("- you invented a metric") < retry.index("ORIGINAL REQUEST")
    assert "rejected by an automatic check" in retry
