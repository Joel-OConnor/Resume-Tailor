"""Command-line interface.

resume-tailor build applications/acme-staff-engineer/resume.md
resume-tailor match applications/acme-staff-engineer/job-description.md
resume-tailor tailor                       every posting in jobs/
resume-tailor tailor path/to/posting.md    one named posting
resume-tailor profile validate
resume-tailor profile render -o profile/MASTER_PROFILE.md
resume-tailor profile schema -o schema/master-profile.schema.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from resume_tailor import __version__
from resume_tailor.agent import build_profile
from resume_tailor.api import create_app
from resume_tailor.errors import RenderError, ResumeTailorError
from resume_tailor.llm import build_model, load_settings
from resume_tailor.match import match_posting, read_posting
from resume_tailor.match import render_json as match_json
from resume_tailor.match import render_markdown as match_markdown
from resume_tailor.match import render_text as match_text
from resume_tailor.profile import DEFAULT_PROFILE_PATH, build_schema, load, render_markdown
from resume_tailor.render import Layout, build
from resume_tailor.render.exporter import is_sectioned, read_source
from resume_tailor.render.polished import DEFAULT_SIDEBAR_SECTIONS
from resume_tailor.service import read_raw_documents, tailor_application

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]

_DEFAULT_MARKDOWN_VIEW = Path("profile/MASTER_PROFILE.md")
_DEFAULT_SCHEMA_PATH = Path("schema/master-profile.schema.json")
DEFAULT_JOBS_DIR = Path("jobs")
POSTING_SUFFIXES = (".md", ".markdown", ".txt", ".text")
"""What counts as a posting inside an inbox folder — everything else there is the user's notes."""

INBOX_GUIDE = "README.md"
"""The inbox's own instructions, which ship with the project and are never a job posting."""


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="resume-tailor",
        description="Build ATS-safe and polished resumes from a structured career profile.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("build", help="render Markdown to .docx and .pdf")
    export.add_argument("files", nargs="+", type=Path, help="markdown file(s) to render")
    export.add_argument(
        "--out-dir", type=Path, default=None, help="write here (default: alongside the source)"
    )
    export.add_argument(
        "--layout",
        type=Layout,
        choices=list(Layout),
        default=Layout.BOTH,
        help="ats = single column for screeners, polished = two column for people (default: both)",
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

    coverage = commands.add_parser(
        "match", help="check a job posting against the profile, with evidence"
    )
    coverage.add_argument("posting", type=Path, help="the job description to check")
    coverage.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    coverage.add_argument("--company", default="", help="the hiring company, if the file omits it")
    coverage.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="text for the terminal, markdown to paste into a fit report, json for tooling",
    )
    coverage.set_defaults(handler=_match)

    apply_ = commands.add_parser(
        "tailor", help="generate tailored applications from job postings (needs an API key)"
    )
    apply_.add_argument(
        "postings",
        nargs="*",
        type=Path,
        help=f"job descriptions, or folders of them (default: everything in {DEFAULT_JOBS_DIR}/)",
    )
    apply_.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    apply_.add_argument("--applications", type=Path, default=Path("applications"))
    apply_.add_argument(
        "--jobs",
        type=Path,
        default=DEFAULT_JOBS_DIR,
        help=f"the inbox scanned when no posting is named (default: {DEFAULT_JOBS_DIR})",
    )
    apply_.add_argument("--no-export", action="store_true", help="skip the .docx/.pdf render")
    apply_.set_defaults(handler=_tailor)

    serve = commands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    serve.add_argument("--applications", type=Path, default=Path("applications"))
    serve.set_defaults(handler=_serve)

    profile = commands.add_parser("profile", help="work with the structured master profile")
    actions = profile.add_subparsers(dest="action", required=True)

    validate = actions.add_parser("validate", help="check the profile against the schema")
    validate.add_argument("path", nargs="?", type=Path, default=DEFAULT_PROFILE_PATH)
    validate.set_defaults(handler=_validate)

    render = actions.add_parser("render", help="write the readable Markdown view of the profile")
    render.add_argument("path", nargs="?", type=Path, default=DEFAULT_PROFILE_PATH)
    render.add_argument("-o", "--out", type=Path, default=_DEFAULT_MARKDOWN_VIEW)
    render.set_defaults(handler=_render)

    generate = actions.add_parser(
        "build", help="draft the profile from profile/raw/ with a model (needs an API key)"
    )
    generate.add_argument("--raw", type=Path, default=Path("profile/raw"))
    generate.add_argument("-o", "--out", type=Path, default=DEFAULT_PROFILE_PATH)
    generate.add_argument(
        "--force",
        action="store_true",
        help="replace an existing profile, keeping a timestamped backup beside it",
    )
    generate.set_defaults(handler=_build_profile)

    schema = actions.add_parser("schema", help="write the JSON Schema for the profile")
    schema.add_argument("-o", "--out", type=Path, default=_DEFAULT_SCHEMA_PATH)
    schema.set_defaults(handler=_schema)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except ResumeTailorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


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


def _match(args: argparse.Namespace) -> int:
    if not args.posting.is_file():
        print(f"error: not a file: {args.posting}", file=sys.stderr)
        return 1
    report = match_posting(read_posting(args.posting), load(args.profile), args.company)
    renderer = {"text": match_text, "markdown": match_markdown, "json": match_json}
    print(renderer[args.format](report), end="")
    return 0


def _tailor(args: argparse.Namespace) -> int:
    """Tailor every named posting, or the whole inbox when none is named.

    One posting per application, and one failure does not end the batch: a posting the model
    cannot honestly satisfy is reported and the rest still run, because the alternative is a user
    who applied to four jobs getting documents for none of them.
    """
    named: list[Path] = args.postings
    postings, failed = _collect_postings(named or [args.jobs])
    if not postings:
        if not failed:
            print(_nothing_to_tailor(named, args.jobs), file=sys.stderr)
        return 1

    # Resolved first, so "there are no postings" never costs an API key to discover.
    model = build_model(load_settings())
    for path in postings:
        print(f"{path}:")
        try:
            application = tailor_application(
                read_posting(path),
                profile_path=args.profile,
                applications_dir=args.applications,
                model=model,
                export=not args.no_export,
            )
        except ResumeTailorError as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"  → {application.directory}")
        for artefact in application.files:
            print(f"    ✓ {artefact.name}")
    return 1 if failed else 0


def _collect_postings(paths: list[Path]) -> tuple[list[Path], bool]:
    """Expand files and inbox folders into postings, reporting anything unusable.

    A named file is taken as a posting whatever it is called; only a *folder* is filtered, so a
    deliberate ``tailor notes.rtf`` still runs while a stray export sitting in the inbox does not
    become an application on its own. The inbox's own README is never a posting — tailoring
    against the instructions that ship with the project is nobody's intent.
    """
    postings: list[Path] = []
    failed = False
    for path in paths:
        if path.is_file():
            postings.append(path)
        elif path.is_dir():
            postings += sorted(
                child
                for child in path.iterdir()
                if child.is_file()
                and not child.name.startswith(".")
                and child.name != INBOX_GUIDE
                and child.suffix.lower() in POSTING_SUFFIXES
            )
        elif path.exists():
            print(f"error: not a file or folder: {path}", file=sys.stderr)
            failed = True
        else:
            print(f"error: not found: {path}", file=sys.stderr)
            failed = True
    # The same posting named twice would tailor twice and write the folder twice over.
    return list(dict.fromkeys(postings)), failed


def _nothing_to_tailor(named: list[Path], jobs: Path) -> str:
    """Explain an empty run, in terms of how the user asked for it."""
    if named:
        return "error: no job descriptions found in the folders given"
    suffixes = ", ".join(POSTING_SUFFIXES)
    return (
        f"error: no job descriptions in {jobs}/ — save a posting there as a {suffixes} file, "
        f"or name one: resume-tailor tailor path/to/posting.md"
    )


def _serve(args: argparse.Namespace) -> int:
    import uvicorn  # noqa: PLC0415 - deferred so the base install needs no web stack

    app = create_app(profile_path=args.profile, applications_dir=args.applications)
    print(f"  → http://{args.host}:{args.port}/docs")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _build_profile(args: argparse.Namespace) -> int:
    """Draft the master profile from the raw folder, without ever silently replacing one."""
    raw = read_raw_documents(args.raw)
    if not raw.documents:
        print(f"error: no readable documents in {args.raw}", file=sys.stderr)
        _report_skipped(raw.skipped)
        return 1
    if args.out.exists() and not args.force:
        print(
            f"error: {args.out} already exists. Building would replace it, losing any correction "
            f"made by hand. Re-run with --force to replace it (a timestamped backup is kept), or "
            f"use -o to write the draft somewhere else.",
            file=sys.stderr,
        )
        return 1

    print(f"  reading {len(raw.documents)} document(s) from {args.raw}")
    for name in raw.documents:
        print(f"    · {name}")
    _report_skipped(raw.skipped)

    yaml_text, usage = build_profile(raw.documents, build_model(load_settings()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if backup := _back_up(args.out):
        print(f"  ✓ {backup}  (previous profile)")
    args.out.write_text(yaml_text, encoding="utf-8")
    print(f"  ✓ {args.out}  ({usage.attempts} attempt(s))")
    print("  review it, then run: make profile-check")
    return 0


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


def _back_up(out: Path) -> Path | None:
    """Copy an existing profile aside before it is replaced, returning where it went."""
    if not out.exists():
        return None
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    backup = out.with_name(f"{out.name}.{stamp}.bak")
    try:
        shutil.copy2(out, backup)
    except OSError as exc:
        msg = f"cannot back up {out}: {exc.strerror or exc}"
        raise RenderError(msg) from exc
    return backup


def _validate(args: argparse.Namespace) -> int:
    profile = load(args.path)
    roles = sum(len(tenure.roles) for tenure in profile.experience)
    technologies = len(
        {item.name.casefold() for group in profile.technologies for item in group.items}
    )
    print(
        f"✓ {args.path} is valid — {len(profile.experience)} employers, {roles} roles, "
        f"{technologies} technologies"
    )
    for note in profile.notes:
        print(f"  · note: {note}")
    return 0


def _render(args: argparse.Namespace) -> int:
    profile = load(args.path)
    _write(args.out, render_markdown(profile))
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
