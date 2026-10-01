"""Command-line interface.

Three commands make things, in the order a user runs them:

    resume-tailor profile build              draft, refine and write output/master-profile.yaml
    resume-tailor resume                     the general resume and the LinkedIn profile
    resume-tailor tailor posting.md          a resume and cover letter for that one job

Each reviews what it wrote before exporting it, and at a terminal asks the questions only the
candidate can answer. The rest are utilities:

    resume-tailor profile validate           check the profile and audit it
    resume-tailor profile render             write the readable Markdown view of the profile
    resume-tailor profile schema             regenerate the JSON Schema
    resume-tailor build resume.md            re-render a hand-edited .md to .docx and .pdf
    resume-tailor relay wait                 (Claude Code) wait for a script's next model request
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from resume_tailor import __version__
from resume_tailor.errors import RenderError, ResumeTailorError
from resume_tailor.llm import (
    build_model,
    load_relay_dir,
    load_settings,
    pending_requests,
    response_for,
    wait_for_request,
)
from resume_tailor.llm.config import DEFAULT_RELAY_DIR
from resume_tailor.match import read_posting
from resume_tailor.paths import (
    APPLICATIONS_FOLDER,
    GENERAL_FOLDER,
    JOB_POSTINGS_DIR,
    PROFILE_VIEW_PATH,
    SCHEMA_PATH,
)
from resume_tailor.profile import DEFAULT_PROFILE_PATH, build_schema, load, render_markdown
from resume_tailor.render import Layout, build
from resume_tailor.render.exporter import is_sectioned, read_source
from resume_tailor.render.polished import DEFAULT_SIDEBAR_SECTIONS
from resume_tailor.review import MAX_QUESTIONS, Answer, format_review, from_findings, review_profile
from resume_tailor.service import (
    DEFAULT_ANSWERS_PATH,
    DEFAULT_CAREER_DIR,
    DEFAULT_OUTPUT_DIR,
    build_master_profile,
    general_application,
    read_raw_documents,
    tailor_application,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from resume_tailor.render import Artifact
    from resume_tailor.review import Question, Review
    from resume_tailor.service import Application, Asker, ProfileBuild, ProfileUpdate

__all__ = ["main"]

_STOP_WORDS = frozenset({"done", "stop", "quit", "q"})
_SECONDS_PER_MINUTE = 60
_WIDTH = 96

_INTERRUPTED = 130
"""What a shell reports for a command stopped with Ctrl-C: 128 plus SIGINT."""

_CALLS_THE_MODEL = "(calls the model set in .env)"
"""Said of every command that needs one: the API with a key, or Claude Code through the relay."""

_EXAMPLE_PROFILE = Path("examples/master-profile.yaml")
"""A complete fictional profile, for trying the tool out before building one."""

_ANSWERS_FILE = DEFAULT_ANSWERS_PATH.name
_YAML_SUFFIXES = frozenset({".yaml", ".yml"})
_BUILD_OUTPUTS = frozenset({".docx", ".pdf", ".html"})
"""What ``build`` writes beside a source: given as the source itself, each is the wrong file."""

_TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".text"})
"""The plain-text files a profile build reads, as ``read_raw_documents`` decides."""

_RELAY_REQUESTS = "*.request.md"
"""Every request in a relay folder, waited on or not (see :mod:`resume_tailor.llm.relay`)."""


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="resume-tailor",
        description="Build a master profile, a general resume and LinkedIn profile, and "
        "tailored applications, from your real career history.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    profile = commands.add_parser("profile", help="build and work with the master profile")
    _add_profile_actions(profile)

    general = commands.add_parser(
        "resume", help=f"write the general resume and the LinkedIn profile {_CALLS_THE_MODEL}"
    )
    _add_output_arguments(general, f"its {GENERAL_FOLDER}/ folder")
    general.set_defaults(handler=_resume)

    job = commands.add_parser(
        "tailor", help=f"write a resume and cover letter for one job posting {_CALLS_THE_MODEL}"
    )
    job.add_argument(
        "posting",
        type=Path,
        help=f"the job description as a .md or .txt file: a path, or a name in {JOB_POSTINGS_DIR}/",
    )
    _add_output_arguments(job, f"{APPLICATIONS_FOLDER}/<company>-<role>/ inside it")
    job.set_defaults(handler=_tailor)

    relay = commands.add_parser(
        "relay",
        help="answer the scripts' requests from Claude Code (RESUME_TAILOR_LLM=claude-code)",
    )
    relay_actions = relay.add_subparsers(dest="action", required=True)
    wait = relay_actions.add_parser(
        "wait", help="wait for the next request, then print its path and where its reply goes"
    )
    wait.add_argument(
        "--dir",
        type=Path,
        default=None,
        help=(
            "the relay folder (default: RESUME_TAILOR_RELAY_DIR from the environment or .env, "
            f"else {DEFAULT_RELAY_DIR})"
        ),
    )
    wait.add_argument(
        "--timeout", type=_minutes, default=30.0, help="minutes to wait (default: 30)"
    )
    wait.set_defaults(handler=_relay_wait)

    export = commands.add_parser("build", help="re-render a resume or cover letter .md")
    export.add_argument("files", nargs="+", type=Path, help="markdown file(s) to render")
    export.add_argument(
        "--out-dir", type=Path, default=None, help="write here (default: alongside the source)"
    )
    export.add_argument(
        "--layout",
        type=_layout,
        choices=list(Layout),
        default=Layout.ATS,
        help=(
            "ats = the single-column resume for screeners and people alike (default), "
            "polished = the two-column design for people only, both = the pair"
        ),
    )
    export.add_argument(
        "--sidebar",
        default=None,
        help=(
            "comma-separated sections placed in the polished layout's left rail "
            f"(default: {', '.join(DEFAULT_SIDEBAR_SECTIONS)})"
        ),
    )
    export.add_argument(
        "--no-pdf",
        action="store_true",
        help=(
            "write only the .docx files; an earlier .pdf or .html of the same name is removed, "
            "so it cannot pass for this version"
        ),
    )
    export.set_defaults(handler=_build)
    return parser


def _add_profile_actions(profile: argparse.ArgumentParser) -> None:
    """Declare the ``profile`` sub-commands: build, validate, render and schema."""
    actions = profile.add_subparsers(dest="action", required=True)

    generate = actions.add_parser(
        "build", help=f"draft and refine the profile from {DEFAULT_CAREER_DIR}/ {_CALLS_THE_MODEL}"
    )
    generate.add_argument(
        "--documents",
        type=Path,
        default=DEFAULT_CAREER_DIR,
        help=f"the folder of career documents to build from (default: {DEFAULT_CAREER_DIR})",
    )
    generate.add_argument(
        "-o",
        "--out",
        type=Path,
        default=DEFAULT_PROFILE_PATH,
        help=f"where to write the profile (default: {DEFAULT_PROFILE_PATH})",
    )
    generate.add_argument(
        "--force",
        action="store_true",
        help="replace an existing profile, keeping a timestamped copy in backups/ beside it",
    )
    _add_question_arguments(generate, answers=None)
    generate.set_defaults(handler=_build_profile)

    validate = actions.add_parser("validate", help="check the profile and audit it")
    validate.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_PROFILE_PATH,
        help=f"the profile to check (default: {DEFAULT_PROFILE_PATH})",
    )
    validate.set_defaults(handler=_validate)

    render = actions.add_parser("render", help="write the readable Markdown view of the profile")
    render.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_PROFILE_PATH,
        help=f"the profile to render (default: {DEFAULT_PROFILE_PATH})",
    )
    render.add_argument(
        "-o",
        "--out",
        type=Path,
        default=PROFILE_VIEW_PATH,
        help=f"where to write the Markdown view (default: {PROFILE_VIEW_PATH})",
    )
    render.set_defaults(handler=_render)

    schema = actions.add_parser("schema", help="write the JSON Schema for the profile")
    schema.add_argument(
        "-o",
        "--out",
        type=Path,
        default=SCHEMA_PATH,
        help=f"where to write the schema (default: {SCHEMA_PATH})",
    )
    schema.set_defaults(handler=_schema)


def _add_output_arguments(parser: argparse.ArgumentParser, where: str) -> None:
    """Declare what the two generating commands share: inputs, outputs, and the questions.

    ``where`` says where under the output folder this command's documents go.
    """
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE_PATH,
        help=f"the master profile to write from (default: {DEFAULT_PROFILE_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"the output folder; the documents go in {where} (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--no-export", action="store_true", help="skip the .docx/.pdf render")
    _add_question_arguments(parser)


def _add_question_arguments(
    parser: argparse.ArgumentParser, *, answers: Path | None = DEFAULT_ANSWERS_PATH
) -> None:
    """Declare the two flags every run that asks questions takes.

    ``answers`` is where the log goes by default. ``None`` puts it in the folder the run reads its
    documents from (see :func:`_answers_log`), which is where the next rebuild looks for it.
    """
    parser.add_argument(
        "--interactive",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="ask the review's questions as it runs (default: when run from a terminal)",
    )
    default = str(answers) if answers is not None else f"{_ANSWERS_FILE} in the --documents folder"
    parser.add_argument(
        "--answers",
        type=Path,
        default=answers,
        help=f"where answers are logged for the next rebuild (default: {default})",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    _keep_output_in_order()
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except ResumeTailorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # Ctrl-C is how a run is stopped on purpose (a relay wait can last an hour), not a crash
        # to debug. Whatever was already written stays written, so this claims nothing about it.
        print("\ninterrupted", file=sys.stderr)
        return _INTERRUPTED


def _keep_output_in_order() -> None:
    """Flush standard output at every newline, so piped output reads in the order it happened.

    Python buffers stdout when it is not a terminal (Claude Code, a pipe, CI) but never stderr, so
    without this every warning and error would print above the progress lines it belongs under.
    """
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)


# --- the three runs -------------------------------------------------------------------------------
def _build_profile(args: argparse.Namespace) -> int:
    """Draft, refine and write the master profile, then ask what it could not settle."""
    documents: Path = args.documents
    if not documents.is_dir():
        print(f"error: {_not_a_documents_folder(documents)}", file=sys.stderr)
        return 1
    raw = read_raw_documents(documents)
    if not raw.documents:
        print(f"error: no readable documents in {documents}", file=sys.stderr)
        _report_unread(documents, raw.skipped)
        return 1
    # Checked before the first model call: the run itself writes the profile only at the end.
    if problem := _cannot_write_profile(args.out, force=args.force):
        print(f"error: {problem}", file=sys.stderr)
        return 1
    print(f"  reading {len(raw.documents)} document(s) from {documents}")
    for name in raw.documents:
        print(f"    · {name}")
    _report_unread(documents, raw.skipped)

    built = build_master_profile(
        raw,
        out=args.out,
        model=build_model(load_settings(), announce=_progress),
        force=args.force,
        ask=_asker(args),
        answers_path=_answers_log(args),
        progress=_progress,
    )
    _print_build(built)
    return 0


def _answers_log(args: argparse.Namespace) -> Path:
    """Return where a profile build logs answers: ``--answers``, else beside its documents.

    The next rebuild from that folder reads every file in it, the log included. Kept anywhere
    else, the answers would be lost the next time the profile is built from the same folder.
    """
    chosen: Path | None = args.answers
    return chosen if chosen is not None else args.documents / _ANSWERS_FILE


def _not_a_documents_folder(documents: Path) -> str:
    """Say what is wrong with a ``--documents`` path that is not a folder."""
    if documents.exists():
        return f"{documents} is a file; --documents takes the folder your career documents are in"
    return (
        f"there is no folder {documents}. Put your career documents there, or point --documents "
        f"at the folder they are in."
    )


def _cannot_write_profile(out: Path, *, force: bool) -> str:
    """Say what would stop a profile build writing ``out``, or return "" when nothing would."""
    if out.is_dir():
        return (
            f"{out} is a folder; -o takes the path of the profile file itself, such as "
            f"{DEFAULT_PROFILE_PATH}"
        )
    if out.exists() and not force:
        return (
            f"{out} already exists. Building would replace it, losing any correction made by "
            f"hand. Re-run with --force (with make: make profile FORCE=--force) to replace it; "
            f"a timestamped backup is kept."
        )
    return _unwritable(out.parent)


def _resume(args: argparse.Namespace) -> int:
    """Write, review and export the general resume and the LinkedIn profile."""
    if problem := _cannot_start(args.profile, args.output):
        print(f"error: {problem}", file=sys.stderr)
        return 1
    model = build_model(load_settings(), announce=_progress)
    application = general_application(
        profile_path=args.profile,
        output_dir=args.output,
        model=model,
        ask=_asker(args),
        answers_path=args.answers,
        export=not args.no_export,
        progress=_progress,
    )
    _print_application(application, args.profile)
    return 0


def _tailor(args: argparse.Namespace) -> int:
    """Write, review and export a resume and cover letter for the one posting named."""
    posting = _find_posting(args.posting)
    if not posting.is_file():
        problem = "not found" if not posting.exists() else "not a file"
        looked = ""
        if not posting.exists() and not args.posting.is_absolute():
            looked = f" (looked for it here and in {JOB_POSTINGS_DIR}/)"
        print(f"error: {problem}: {posting}{looked}", file=sys.stderr)
        return 1
    # A posting that is not text (a PDF, a Word file) raises a PostingError, which main()
    # reports like any other; only the filesystem's own refusal needs saying here.
    try:
        text = read_posting(posting)
    except OSError as exc:
        print(f"error: cannot read {posting}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    if not text.strip():
        print(f"error: {posting} is empty; paste the job description into it", file=sys.stderr)
        return 1
    if problem := _cannot_start(args.profile, args.output / APPLICATIONS_FOLDER):
        print(f"error: {problem}", file=sys.stderr)
        return 1
    # Resolved only once the posting, the profile and the output folder are known to be usable,
    # so a typo never costs a model call.
    model = build_model(load_settings(), announce=_progress)
    application = tailor_application(
        text,
        profile_path=args.profile,
        output_dir=args.output,
        model=model,
        ask=_asker(args),
        answers_path=args.answers,
        export=not args.no_export,
        progress=_progress,
    )
    _print_application(application, args.profile)
    return 0


def _find_posting(posting: Path) -> Path:
    """Return ``posting``, or the file of that name in the job-postings folder if only it exists.

    So ``make tailor JOB=stripe.md`` works for a posting saved where the README says to save it.
    """
    if posting.exists() or posting.is_absolute():
        return posting
    saved = JOB_POSTINGS_DIR / posting
    return saved if saved.exists() else posting


def _cannot_start(profile: Path, folder: Path) -> str:
    """Say what would stop a run that writes into ``folder``, or return "" when nothing would.

    Checked before the first model call. The run reads the profile first, but it reaches the
    folder only at the very end, once every call has been made (and, on the API, paid for).
    """
    if not profile.exists():
        command = (
            "make profile"
            if profile == DEFAULT_PROFILE_PATH
            else f"resume-tailor profile build -o {profile}"
        )
        return (
            f"there is no profile at {profile} yet. Build it from your documents with "
            f"`{command}`, or copy {_EXAMPLE_PROFILE} there to try the tool on an example."
        )
    return _unwritable(folder)


def _unwritable(folder: Path) -> str:
    """Say what would stop anything being written into ``folder``, or return "" when nothing would.

    A folder that does not exist yet is fine if it can be created, so the nearest part of the
    path that does exist is the one judged.
    """
    nearest = folder
    while not nearest.exists() and nearest != nearest.parent:
        nearest = nearest.parent
    if nearest.is_dir():
        writable = os.access(nearest, os.W_OK | os.X_OK)
        return "" if writable else f"cannot write to {folder}: {nearest} is not writable"
    if nearest == folder:
        return f"{folder} is a file, not a folder"
    return (
        f"cannot write to {folder}: {nearest} is a file, not a folder" if nearest.exists() else ""
    )


# --- asking ---------------------------------------------------------------------------------------
def _asker(args: argparse.Namespace) -> Asker | None:
    """Return the terminal question cycle, or ``None`` when nobody is there to answer."""
    interactive = args.interactive if args.interactive is not None else sys.stdin.isatty()
    return _ask_in_terminal if interactive else None


def _ask_in_terminal(questions: tuple[Question, ...]) -> tuple[Answer, ...]:
    """Ask ``questions`` one by one; Enter skips one, and "done", Ctrl-C or end of input stops."""
    count = len(questions)
    plural = "" if count == 1 else "s"
    print(
        f"\n  {count} question{plural} before the final version. Answer in a sentence or two; "
        'Enter skips, "done" finishes.'
    )
    answers: list[Answer] = []
    for index, question in enumerate(questions, start=1):
        print()
        print(_wrap(f"[{index}/{count}] {question.text}", "  ", "        "))
        if question.about:
            print(_wrap(f'"{question.about}"', "        ", "        "))
        try:
            reply = input("    > ").strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            # At a question, Ctrl-C means "stop asking", not "throw away what I already typed".
            print(_stopped_asking(answers))
            break
        if reply.casefold() in _STOP_WORDS:
            break
        answers.append(Answer(question, reply))
    return tuple(answers)


def _stopped_asking(answers: Sequence[Answer]) -> str:
    """Say that Ctrl-C ended the questions, what was kept, and how to stop the run itself."""
    given = sum(1 for answer in answers if answer.text)
    kept = f" Keeping your {given} answer{'' if given == 1 else 's'}." if given else ""
    return f"\n  Stopped asking.{kept} Ctrl-C again stops the run."


# --- reporting ------------------------------------------------------------------------------------
def _progress(message: str) -> None:
    print(f"  … {message}", flush=True)


def _print_build(built: ProfileBuild) -> None:
    kept = (
        f"  (previous profile kept as {built.backup.parent.name}/{built.backup.name})"
        if built.backup
        else ""
    )
    print(f"  ✓ {built.path}{kept}")
    if built.refine_error:
        # Printed as the build words it: a refinement that failed its checks and one that never
        # ran (declined, timed out, out of credit) need different next steps.
        print(_wrap(f"! {built.refine_error}", "  ", "    "), file=sys.stderr)
    _print_lines("Refined", built.changes)
    _print_lines("What changed", built.difference)
    if built.update is not None:
        _print_update(built.update, built.path)
    if built.review.advice:
        print()
        _print_review(built.review, "Still worth a look")
    if still_open := from_findings(built.review.findings):
        more = len(still_open) - MAX_QUESTIONS
        rest = (
            f" {more} more are in its notes; `resume-tailor profile validate` lists them."
            if more > 0
            else ""
        )
        # A note itself is never printed, but the value it questions is, as the profile has it.
        _print_open(
            still_open[:MAX_QUESTIONS],
            f"Notes never appear in a resume, but what the profile records now does, even where "
            f"a note questions it. Settle one by recording the fact where it belongs in "
            f"{built.path} and deleting its note.{rest}",
        )
    print("\n  next: read it over (.venv/bin/resume-tailor profile render), then run: make resume")


def _print_application(application: Application, profile_path: Path) -> None:
    if application.fit:
        print()
        print(_wrap(f"Fit: {application.fit}", "  ", "       "))
    if application.update is not None:
        _print_update(application.update, profile_path)
    for problem in application.problems:
        print(_wrap(f"! {problem}", "  ", "    "), file=sys.stderr)
    print(f"\n  → {application.directory}")
    for artefact in application.files:
        print(f"    ✓ {artefact.name}")
    review = application.review
    if review.applied or review.advice:
        print()
        _print_review(review, "Review")
    if application.questions and not application.asked:
        _print_open(
            application.questions,
            f"Run it again at a terminal to answer them as it goes, or add the facts to "
            f"{profile_path} and run it again.",
        )


def _print_update(update: ProfileUpdate, profile_path: Path) -> None:
    if update.error:
        # The error ends by saying where the answers are logged, so this does not say it again.
        print(
            _wrap(
                f"! your answers could not be recorded in {profile_path} automatically: "
                f"{update.error}",
                "  ",
                "    ",
            ),
            file=sys.stderr,
        )
        return
    plural = "" if len(update.answers) == 1 else "s"
    print(f"\n  ✓ recorded {len(update.answers)} answer{plural} in {profile_path}")
    for line in update.changes:
        print(f"      {line}")


def _print_open(questions: Sequence[Question], hint: str) -> None:
    print("\n  Open questions (the answers would make this stronger):")
    for question in questions:
        print(_wrap(f"? {question.text}", "    ", "      "))
        if question.about:
            print(_wrap(f'"{question.about}"', "      ", "      "))
    print(_wrap(f"→ {hint}", "  ", "    "))


def _print_lines(title: str, lines: Sequence[str]) -> None:
    if not lines:
        return
    print(f"\n  {title}:")
    for line in lines:
        print(f"    {line}")


def _print_review(review: Review, title: str) -> None:
    """Print a review indented like the rest of a run's report."""
    print(textwrap.indent(format_review(review, title=title), "  "), end="")


def _wrap(text: str, first: str, rest: str) -> str:
    # Never break at a hyphen: a path split across two lines can no longer be copied.
    return textwrap.fill(
        text,
        width=_WIDTH,
        initial_indent=first,
        subsequent_indent=rest,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _report_unread(folder: Path, skipped: Sequence[str]) -> None:
    """Name every file in ``folder`` that produced no text, and every folder inside it.

    Silence here is the failure mode that matters: a user who dropped in a scanned resume and was
    told "reading 2 documents" has no way to know the one they cared about was never read. The
    same goes for a folder of old resumes: only the files directly in ``folder`` are read.
    """
    for name in skipped:
        message = f"! {name}: no text could be read from it. {_why_unread(name)}"
        print(_wrap(message, "  ", "    "), file=sys.stderr)
    inner = (path.name for path in folder.iterdir() if path.is_dir())
    for name in sorted(name for name in inner if not name.startswith(".")):
        message = f"! {name}/ is a folder, and only the files directly in {folder} are read"
        print(_wrap(message, "  ", "    "), file=sys.stderr)


def _why_unread(name: str) -> str:
    """Say what most likely kept any text from coming out of ``name``, going by its kind."""
    suffix = Path(name).suffix.casefold()
    if suffix == ".pdf":
        return (
            "A scanned PDF has no text in it (nor does a locked or damaged one): add a text or "
            "Word version."
        )
    if suffix == ".docx":
        return "The Word file is empty or damaged: re-save it, or add a text version."
    if suffix in _TEXT_SUFFIXES:
        return "It is empty, or its text is in an encoding this cannot read: re-save it as UTF-8."
    return "Only .pdf, .docx, .md and .txt files are read: save a copy in one of those."


# --- utilities ------------------------------------------------------------------------------------
def _relay_wait(args: argparse.Namespace) -> int:
    """Wait for a script's next model request, then say where it is and where to answer it."""
    directory: Path = args.dir or load_relay_dir()
    request = wait_for_request(directory, timeout=args.timeout * _SECONDS_PER_MINUTE)
    if request is None:
        print(f"no request waiting in {directory} after {args.timeout:g} minutes", file=sys.stderr)
        if stale := _stale_requests(directory):
            print(
                f"  stale: {stale} request file(s) left there by scripts that stopped before "
                f"tidying up, safe to delete once no script is running",
                file=sys.stderr,
            )
        return 1
    print(f"request: {request}")
    print(f"reply to: {response_for(request)}")
    return 0


def _stale_requests(directory: Path) -> int:
    """Count the requests in ``directory`` that no script is waiting on any more.

    A script stopped before it could tidy up leaves its request in the folder, and the wait
    rightly passes over it. Without a word about them, "no request waiting" seems to contradict
    the files in plain sight.
    """
    waiting = set(pending_requests(directory))
    return sum(1 for request in directory.glob(_RELAY_REQUESTS) if request not in waiting)


def _minutes(text: str) -> float:
    """Parse a timeout for argparse: a positive number of minutes."""
    try:
        value = float(text)
    except ValueError:
        msg = f"expected a number of minutes, got {text!r}"
        raise argparse.ArgumentTypeError(msg) from None
    if value <= 0:
        msg = f"expected a positive number of minutes, got {value:g}"
        raise argparse.ArgumentTypeError(msg)
    return value


def _validate(args: argparse.Namespace) -> int:
    """Validate the profile, summarise it, and print what its audit still flags."""
    profile = load(args.path)
    roles = sum(len(tenure.roles) for tenure in profile.experience)
    technologies = len(
        {item.name.casefold() for group in profile.technologies for item in group.items}
    )
    print(
        f"✓ {args.path} is valid: {len(profile.experience)} employers, {roles} roles, "
        f"{technologies} technologies"
    )
    audit: Review = review_profile(profile)
    if audit.advice:
        print(format_review(audit, title="Still worth a look"), end="")
    for question in audit.questions:
        print(f"  ? {question.message}")
    return 0


def _render(args: argparse.Namespace) -> int:
    if problem := _replaces_a_profile(args.out, args.path):
        print(
            f"error: {problem}; writing the Markdown view there would replace it. Choose another "
            f"-o, such as {PROFILE_VIEW_PATH}",
            file=sys.stderr,
        )
        return 1
    _write(args.out, render_markdown(load(args.path), source=args.path))
    return 0


def _schema(args: argparse.Namespace) -> int:
    if problem := _replaces_a_profile(args.out):
        print(
            f"error: {problem}; writing the schema there would replace it. Choose another -o, "
            f"such as {SCHEMA_PATH}",
            file=sys.stderr,
        )
        return 1
    _write(args.out, json.dumps(build_schema(), indent=2) + "\n")
    return 0


def _replaces_a_profile(out: Path, source: Path | None = None) -> str:
    """Say why writing ``out`` would destroy a profile, or return "" when it would not.

    Neither command writes YAML, so an existing YAML file at ``out`` can only be there by mistake,
    most likely the profile itself: one slip of ``-o`` would replace the single source of truth.
    """
    if source is not None and _same_file(out, source):
        return f"{out} is the profile being rendered"
    if out.suffix.casefold() in _YAML_SUFFIXES and out.is_file():
        return f"{out} is a YAML file, most likely a profile"
    return ""


def _same_file(first: Path, second: Path) -> bool:
    """Report whether two paths name one existing file, however each is spelled."""
    try:
        return first.samefile(second)
    except OSError:
        return False


def _write(out: Path, text: str) -> None:
    """Write a generated file, reporting a filesystem problem as one clean line."""
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    except OSError as exc:
        msg = f"cannot write {out}: {exc.strerror or exc}"
        raise RenderError(msg) from exc
    print(f"  ✓ {out}")


def _build(args: argparse.Namespace) -> int:
    chosen: str | None = args.sidebar
    sidebar = DEFAULT_SIDEBAR_SECTIONS
    if chosen is not None:
        sidebar = tuple(part.strip() for part in chosen.split(",") if part.strip())
    files: list[Path] = args.files
    sources = _usable_sources(files)
    failed = len(sources) < len(files)
    out_dir: Path | None = args.out_dir
    if out_dir is not None and (problem := _unwritable(out_dir)):
        print(f"error: {problem}", file=sys.stderr)
        return 1
    if clash := _clashing_outputs(sources, out_dir, args.layout):
        print(
            f"error: {clash} would be written twice: two sources render to the same file, so "
            "build them separately or into different directories",
            file=sys.stderr,
        )
        return 1

    for path in sources:
        print(f"{path}:")
        # One bad source must not abandon the rest of a batch.
        try:
            artifacts = build(
                path,
                out_dir=out_dir,
                layout=args.layout,
                sidebar_sections=sidebar,
                pdf=not args.no_pdf,
            )
        except ResumeTailorError as exc:
            print(f"error: {_with_source(path, exc)}", file=sys.stderr)
            failed = True
            continue
        if chosen is not None:
            _warn_unused_sidebar(path, sidebar, artifacts)
        for artifact in artifacts:
            mark = "✓" if artifact.ok else "!"
            note = "" if artifact.ok else f"  ({artifact.reason})"
            print(f"  {mark} {artifact.path}{note}")
            failed = failed or not artifact.ok
    return 1 if failed else 0


def _layout(text: str) -> Layout:
    """Parse ``--layout`` for argparse, in any letter case."""
    try:
        return Layout(text.casefold())
    except ValueError:
        msg = f"choose from {', '.join(Layout)}, not {text!r}"
        raise argparse.ArgumentTypeError(msg) from None


def _usable_sources(files: Sequence[Path]) -> list[Path]:
    """Return the files ``build`` can render, printing why each of the others cannot be used."""
    usable: list[Path] = []
    for path in files:
        if problem := _unusable(path):
            print(f"error: {problem}", file=sys.stderr)
        else:
            usable.append(path)
    return usable


def _unusable(path: Path) -> str:
    """Say why ``path`` cannot be a source for ``build``, or return "" when it can.

    A ``.docx``, ``.pdf`` or ``.html`` is one of build's own outputs. Passed by mistake, it would
    get advice about text encodings; worse, a Markdown file misnamed that way is the very name
    build writes, so building it would overwrite or delete the source.
    """
    if not path.is_file():
        return f"{'not found' if not path.exists() else 'not a file'}: {path}"
    suffix = path.suffix.casefold()
    if suffix not in _BUILD_OUTPUTS:
        return ""
    markdown = path.with_suffix(".md")
    instead = (
        f"pass {markdown}"
        if markdown.is_file()
        else "pass the .md it was built from, or rename this file to .md if it holds Markdown"
    )
    return f"{path} is a {suffix} file, and build renders the Markdown source: {instead}"


def _with_source(path: Path, error: ResumeTailorError) -> str:
    """Return ``error`` as one line naming its source once, not twice."""
    message = str(error)
    return message if str(path) in message else f"{path}: {message}"


def _warn_unused_sidebar(
    path: Path, sidebar: tuple[str, ...], artifacts: Sequence[Artifact]
) -> None:
    """Warn about an explicit --sidebar name no heading matches, which is usually a typo.

    Only for a name the user typed, and only for a document that got the polished layout: the
    rail means nothing to the single-column one, which is all a cover letter ever gets. The
    default list deliberately covers headings most resumes do not have, so warning about it would
    be noise on every single build.
    """
    if not any(artifact.layout is Layout.POLISHED for artifact in artifacts):
        return
    try:
        headings = {group.key for group in read_source(path).groups() if group.title}
    except ResumeTailorError:  # pragma: no cover - build() just parsed this file successfully
        return
    if unmatched := [name for name in sidebar if name.casefold() not in headings]:
        print(
            f"  warning: --sidebar {', '.join(unmatched)} matched no section in {path.name}",
            file=sys.stderr,
        )


def _clashing_outputs(files: Sequence[Path], out_dir: Path | None, layout: Layout) -> str:
    """Name an output file two sources would both write, or an empty string if there is none.

    Compares the *rendered* names, not the source stems: the polished pass suffixes
    ``-polished``, so ``resume.md`` and ``resume-polished.md`` collide even though their stems
    differ. Sources are resolved first, so the same file named two ways is not a clash; names are
    compared case-insensitively, because on macOS and Windows ``Resume.docx`` and ``resume.docx``
    are one file and the overwrite this guard exists to prevent would happen silently.
    """
    seen: dict[tuple[Path, str], Path] = {}
    for path in files:
        resolved = _resolve(path)
        directory = _resolve(out_dir or path.parent)
        for stem in _output_stems(path, layout):
            key = (directory, stem.casefold())
            if key in seen and seen[key] != resolved:
                return stem
            seen[key] = resolved
    return ""


def _resolve(path: Path) -> Path:
    """Normalise a path for comparison, tolerating one that does not exist yet."""
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - platform-dependent
        return path.absolute()


def _output_stems(path: Path, layout: Layout) -> list[str]:
    """Return the file stems ``path`` renders to under ``layout``."""
    stems = []
    if layout in (Layout.ATS, Layout.BOTH):
        stems.append(path.stem)
    if layout is Layout.POLISHED or (layout is Layout.BOTH and _has_sections(path)):
        stems.append(f"{path.stem}-polished")
    return stems


def _has_sections(path: Path) -> bool:
    """Detect a resume the same way ``build`` does.

    ``build`` downgrades a section-less document to the ATS layout alone, so a pair of cover
    letters must not be refused for a collision that cannot happen. This asks the real parser
    rather than scanning for ``## ``: a heading inside the template's leading HTML comment, or
    one written with leading spaces, would otherwise make the guard and the builder disagree.
    """
    try:
        return is_sectioned(read_source(path))
    except ResumeTailorError:
        # The clash check runs before the build reads each source, so a file it cannot read
        # (not UTF-8, say) lands here. Assume a resume so the guard stays conservative; the
        # build then tells the user the real problem.
        return True
