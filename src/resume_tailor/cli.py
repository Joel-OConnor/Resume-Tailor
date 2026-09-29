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
import json
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
    response_for,
    wait_for_request,
)
from resume_tailor.match import read_posting
from resume_tailor.paths import JOB_POSTINGS_DIR, PROFILE_VIEW_PATH, SCHEMA_PATH
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

    from resume_tailor.review import Question, Review
    from resume_tailor.service import Application, Asker, ProfileBuild, ProfileUpdate

__all__ = ["main"]

_STOP_WORDS = frozenset({"done", "stop", "quit", "q"})
_SECONDS_PER_MINUTE = 60
_WIDTH = 96


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
        "resume", help="write the general resume and the LinkedIn profile (needs an API key)"
    )
    _add_output_arguments(general)
    general.set_defaults(handler=_resume)

    job = commands.add_parser(
        "tailor", help="write a resume and cover letter for one job posting (needs an API key)"
    )
    job.add_argument(
        "posting",
        type=Path,
        help=f"the job description as a .md or .txt file: a path, or a name in {JOB_POSTINGS_DIR}/",
    )
    _add_output_arguments(job)
    job.set_defaults(handler=_tailor)

    relay = commands.add_parser(
        "relay",
        help="answer the scripts' requests from Claude Code (RESUME_TAILOR_LLM=claude-code)",
    )
    relay_actions = relay.add_subparsers(dest="action", required=True)
    wait = relay_actions.add_parser(
        "wait", help="wait for the next request, then print it and where its reply goes"
    )
    wait.add_argument(
        "--dir", type=Path, default=None, help="the relay folder (default: from .env)"
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
        type=Layout,
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
    export.add_argument("--no-pdf", action="store_true", help="write only the .docx files")
    export.set_defaults(handler=_build)
    return parser


def _add_profile_actions(profile: argparse.ArgumentParser) -> None:
    """Declare the ``profile`` sub-commands: build, validate, render and schema."""
    actions = profile.add_subparsers(dest="action", required=True)

    generate = actions.add_parser(
        "build", help=f"draft and refine the profile from {DEFAULT_CAREER_DIR}/ (needs an API key)"
    )
    generate.add_argument(
        "--documents",
        type=Path,
        default=DEFAULT_CAREER_DIR,
        help=f"the career documents to build from (default: {DEFAULT_CAREER_DIR})",
    )
    generate.add_argument("-o", "--out", type=Path, default=DEFAULT_PROFILE_PATH)
    generate.add_argument(
        "--force",
        action="store_true",
        help="replace an existing profile, keeping a timestamped copy in backups/ beside it",
    )
    _add_question_arguments(generate)
    generate.set_defaults(handler=_build_profile)

    validate = actions.add_parser("validate", help="check the profile and audit it")
    validate.add_argument("path", nargs="?", type=Path, default=DEFAULT_PROFILE_PATH)
    validate.set_defaults(handler=_validate)

    render = actions.add_parser("render", help="write the readable Markdown view of the profile")
    render.add_argument("path", nargs="?", type=Path, default=DEFAULT_PROFILE_PATH)
    render.add_argument("-o", "--out", type=Path, default=PROFILE_VIEW_PATH)
    render.set_defaults(handler=_render)

    schema = actions.add_parser("schema", help="write the JSON Schema for the profile")
    schema.add_argument("-o", "--out", type=Path, default=SCHEMA_PATH)
    schema.set_defaults(handler=_schema)


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare what the two generating commands share: inputs, outputs, and the questions."""
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"where the documents are written (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--no-export", action="store_true", help="skip the .docx/.pdf render")
    _add_question_arguments(parser)


def _add_question_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare the two flags every run that asks questions takes."""
    parser.add_argument(
        "--interactive",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="ask the review's questions as it runs (default: when run from a terminal)",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        default=DEFAULT_ANSWERS_PATH,
        help=f"where answers are logged for the next rebuild (default: {DEFAULT_ANSWERS_PATH})",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except ResumeTailorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


# --- the three runs -------------------------------------------------------------------------------
def _build_profile(args: argparse.Namespace) -> int:
    """Draft, refine and write the master profile, then ask what it could not settle."""
    raw = read_raw_documents(args.documents)
    if not raw.documents:
        print(f"error: no readable documents in {args.documents}", file=sys.stderr)
        _report_skipped(raw.skipped)
        return 1
    if args.out.exists() and not args.force:
        print(
            f"error: {args.out} already exists. Building would replace it, losing any correction "
            f"made by hand. Re-run with --force to replace it (a timestamped backup is kept).",
            file=sys.stderr,
        )
        return 1
    print(f"  reading {len(raw.documents)} document(s) from {args.documents}")
    for name in raw.documents:
        print(f"    · {name}")
    _report_skipped(raw.skipped)

    built = build_master_profile(
        raw,
        out=args.out,
        model=build_model(load_settings(), announce=_progress),
        force=args.force,
        ask=_asker(args),
        answers_path=args.answers,
        progress=_progress,
    )
    _print_build(built)
    return 0


def _resume(args: argparse.Namespace) -> int:
    """Write, review and export the general resume and the LinkedIn profile."""
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
        print(f"error: {problem}: {posting}", file=sys.stderr)
        return 1
    try:
        text = read_posting(posting)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read {posting}: {exc}", file=sys.stderr)
        return 1
    if not text.strip():
        print(f"error: {posting} is empty; paste the job description into it", file=sys.stderr)
        return 1
    # Resolved only once the posting is known to be usable, so a typo never costs an API call.
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


# --- asking ---------------------------------------------------------------------------------------
def _asker(args: argparse.Namespace) -> Asker | None:
    """Return the terminal question cycle, or ``None`` when nobody is there to answer."""
    interactive = args.interactive if args.interactive is not None else sys.stdin.isatty()
    return _ask_in_terminal if interactive else None


def _ask_in_terminal(questions: tuple[Question, ...]) -> tuple[Answer, ...]:
    """Ask ``questions`` one by one; Enter skips one, "done" or end of input stops."""
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
        if reply.casefold() in _STOP_WORDS:
            break
        answers.append(Answer(question, reply))
    return tuple(answers)


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
        print(
            _wrap(
                "! refining did not pass its checks, so the checked draft was written as it "
                f"is: {built.refine_error}",
                "  ",
                "    ",
            ),
            file=sys.stderr,
        )
    _print_lines("Refined", built.changes)
    _print_lines("What changed", built.difference)
    if built.update is not None:
        _print_update(built.update, built.path)
    if built.review.advice:
        print()
        print(format_review(built.review, title="Still worth a look"), end="")
    if still_open := from_findings(built.review.findings):
        more = len(still_open) - MAX_QUESTIONS
        rest = (
            f" {more} more are in its notes; `resume-tailor profile validate` lists them."
            if more > 0
            else ""
        )
        _print_open(
            still_open[:MAX_QUESTIONS],
            f"Until they are settled these stay out of every resume. Settle one by recording "
            f"the fact where it belongs in {built.path} and deleting its note.{rest}",
        )
    print("\n  next: read it over (resume-tailor profile render), then run: make resume")


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
        print(format_review(review, title="Review"), end="")
    if application.questions and not application.asked:
        _print_open(
            application.questions,
            f"Run it again at a terminal to answer them as it goes, or add the facts to "
            f"{profile_path} and run it again.",
        )


def _print_update(update: ProfileUpdate, profile_path: Path) -> None:
    if update.error:
        print(
            _wrap(
                f"! your answers are saved in the answers log, but could not be recorded in "
                f"{profile_path} automatically: {update.error}",
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


def _report_skipped(skipped: tuple[str, ...]) -> None:
    """Name every raw file that produced no text.

    Silence here is the failure mode that matters: a user who dropped in a scanned resume and was
    told "reading 2 documents" has no way to know the one they cared about was never read.
    """
    for name in skipped:
        print(
            f"  ! {name}: no text could be read from it — if it is a scan, add a text or Word "
            f"version instead",
            file=sys.stderr,
        )


# --- utilities ------------------------------------------------------------------------------------
def _relay_wait(args: argparse.Namespace) -> int:
    """Wait for a script's next model request, then say where it is and where to answer it."""
    directory: Path = args.dir or load_relay_dir()
    request = wait_for_request(directory, timeout=args.timeout * _SECONDS_PER_MINUTE)
    if request is None:
        print(f"no request waiting in {directory} after {args.timeout:g} minutes", file=sys.stderr)
        return 1
    print(f"request: {request}")
    print(f"reply to: {response_for(request)}")
    return 0


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
        f"✓ {args.path} is valid — {len(profile.experience)} employers, {roles} roles, "
        f"{technologies} technologies"
    )
    audit: Review = review_profile(profile)
    if audit.advice:
        print(format_review(audit, title="Still worth a look"), end="")
    for question in audit.questions:
        print(f"  ? {question.message}")
    return 0


def _render(args: argparse.Namespace) -> int:
    _write(args.out, render_markdown(load(args.path)))
    return 0


def _schema(args: argparse.Namespace) -> int:
    _write(args.out, json.dumps(build_schema(), indent=2) + "\n")
    return 0


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
    failed = _report_unusable(files)
    if clash := _clashing_outputs(args):
        print(
            f"error: {clash} would be written twice — two sources render to the same file; "
            "build them separately or into different directories",
            file=sys.stderr,
        )
        return 1

    for path in files:
        if not path.is_file():
            continue
        print(f"{path}:")
        # One bad source must not abandon the rest of a batch.
        try:
            artifacts = build(
                path,
                out_dir=args.out_dir,
                layout=args.layout,
                sidebar_sections=sidebar,
                pdf=not args.no_pdf,
            )
        except ResumeTailorError as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            failed = True
            continue
        if chosen is not None:
            _warn_unused_sidebar(path, sidebar, args.layout)
        for artifact in artifacts:
            mark = "✓" if artifact.ok else "!"
            note = "" if artifact.ok else f"  ({artifact.reason})"
            print(f"  {mark} {artifact.path}{note}")
            failed = failed or not artifact.ok
    return 1 if failed else 0


def _report_unusable(files: list[Path]) -> bool:
    """Print a message for every path that cannot be built; True if any was reported."""
    unusable = False
    for path in files:
        if path.is_file():
            continue
        problem = "not found" if not path.exists() else "not a file"
        print(f"error: {problem}: {path}", file=sys.stderr)
        unusable = True
    return unusable


def _warn_unused_sidebar(path: Path, sidebar: tuple[str, ...], layout: Layout) -> None:
    """Warn about an explicit --sidebar name no heading matches — usually a typo.

    Only for a name the user typed. The default list deliberately covers headings most resumes
    do not have, so warning about it would be noise on every single build.
    """
    if layout is Layout.ATS:
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


def _clashing_outputs(args: argparse.Namespace) -> str:
    """Name an output file two sources would both write, or an empty string if there is none.

    Compares the *rendered* names, not the source stems: the polished pass suffixes
    ``-polished``, so ``resume.md`` and ``resume-polished.md`` collide even though their stems
    differ. Sources are resolved first, so the same file named two ways is not a clash; names are
    compared case-insensitively, because on macOS and Windows ``Resume.docx`` and ``resume.docx``
    are one file and the overwrite this guard exists to prevent would happen silently.
    """
    files: list[Path] = args.files
    seen: dict[tuple[Path, str], Path] = {}
    for path in files:
        resolved = _resolve(path)
        directory = _resolve(args.out_dir or path.parent)
        for stem in _output_stems(path, args.layout):
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
        # The clash check runs over every argument, including one that turns out to be a
        # directory. Assume a resume so the guard stays conservative; _report_unusable has
        # already told the user the real problem.
        return True
