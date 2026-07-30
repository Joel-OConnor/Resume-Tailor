"""Command-line interface.

resume-tailor build applications/acme-staff-engineer/resume.md
resume-tailor profile validate
resume-tailor profile render -o profile/MASTER_PROFILE.md
resume-tailor profile schema -o schema/master-profile.schema.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from resume_tailor import __version__
from resume_tailor.errors import ResumeTailorError
from resume_tailor.profile import DEFAULT_PROFILE_PATH, build_schema, load, render_markdown
from resume_tailor.render import Layout, build
from resume_tailor.render.polished import DEFAULT_SIDEBAR_SECTIONS

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]

_DEFAULT_MARKDOWN_VIEW = Path("profile/MASTER_PROFILE.md")
_DEFAULT_SCHEMA_PATH = Path("schema/master-profile.schema.json")


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
        default=",".join(DEFAULT_SIDEBAR_SECTIONS),
        help="comma-separated sections placed in the polished layout's left rail",
    )
    export.add_argument("--no-pdf", action="store_true", help="write only the .docx files")
    export.set_defaults(handler=_build)

    profile = commands.add_parser("profile", help="work with the structured master profile")
    actions = profile.add_subparsers(dest="action", required=True)

    validate = actions.add_parser("validate", help="check the profile against the schema")
    validate.add_argument("path", nargs="?", type=Path, default=DEFAULT_PROFILE_PATH)
    validate.set_defaults(handler=_validate)

    render = actions.add_parser("render", help="write the readable Markdown view of the profile")
    render.add_argument("path", nargs="?", type=Path, default=DEFAULT_PROFILE_PATH)
    render.add_argument("-o", "--out", type=Path, default=_DEFAULT_MARKDOWN_VIEW)
    render.set_defaults(handler=_render)

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
    sidebar = tuple(part.strip() for part in args.sidebar.split(",") if part.strip())
    missing = [path for path in args.files if not path.is_file()]
    for path in missing:
        print(f"error: not found: {path}", file=sys.stderr)
    if clash := _clashing_stems(args):
        print(
            f"error: {clash} would be written twice — two sources share a name under --out-dir; "
            "build them separately or into different directories",
            file=sys.stderr,
        )
        return 1
    for path in args.files:
        if path in missing:
            continue
        print(f"{path}:")
        for artifact in build(
            path,
            out_dir=args.out_dir,
            layout=args.layout,
            sidebar_sections=sidebar,
            pdf=not args.no_pdf,
        ):
            mark = "✓" if artifact.ok else "!"
            note = "" if artifact.ok else "  (no Chrome found — open it and print to PDF)"
            print(f"  {mark} {artifact.path}{note}")
    return 1 if missing else 0


def _clashing_stems(args: argparse.Namespace) -> str:
    """Name a stem that two sources would both write to, or an empty string if there is none.

    Only possible with ``--out-dir``: without it each file lands beside its own source.
    """
    if args.out_dir is None:
        return ""
    files: list[Path] = args.files
    seen: set[str] = set()
    for path in files:
        if path.stem in seen:
            return path.stem
        seen.add(path.stem)
    return ""


def _validate(args: argparse.Namespace) -> int:
    profile = load(args.path)
    roles = sum(len(tenure.roles) for tenure in profile.experience)
    technologies = len({name.casefold() for name in profile.technology_names()})
    print(
        f"✓ {args.path} is valid — {len(profile.experience)} employers, {roles} roles, "
        f"{technologies} technologies"
    )
    for note in profile.notes:
        print(f"  · note: {note}")
    return 0


def _render(args: argparse.Namespace) -> int:
    profile = load(args.path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(profile), encoding="utf-8")
    print(f"  ✓ {args.out}")
    return 0


def _schema(args: argparse.Namespace) -> int:
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(build_schema(), indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ {args.out}")
    return 0
