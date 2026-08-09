from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qa_platform.pipeline.config import load_qa_pipeline_config
from qa_platform.pipeline.doctor import format_doctor_result, run_doctor
from qa_platform.pipeline.orchestrator import run_qa_pipeline
from qa_platform.shared.paths import default_workspace_root, resolve_workspace_root


DEFAULT_CONFIG_RELATIVE_PATH = Path("config") / "qa_pipeline.local.json"


def default_config_path(workspace_root: Path | None = None) -> Path:
    root = workspace_root if workspace_root is not None else default_workspace_root()
    return root / DEFAULT_CONFIG_RELATIVE_PATH


def _default_config_payload(workspace_root: Path) -> dict[str, object]:
    return {
        "project": {
            "book_id": "python_junior",
            "chapter_number": 1,
            "python_version": "3.11",
        },
        "paths": {
            "workspace_root": str(workspace_root),
            "input_pdf": "input/chapter01.pdf",
            "output_root": "extracted_blocks",
            "work_root": "run/document_extraction",
            "run_root": "run/qa_pipeline",
        },
    }


class _ParserExit(Exception):
    def __init__(self, status: int) -> None:
        self.status = status


class _ArgumentParser(argparse.ArgumentParser):
    def exit(self, status: int = 0, message: str | None = None) -> None:
        if message:
            self._print_message(message, sys.stderr)
        raise _ParserExit(status)


def _load_config_from_path(
    config_path: Path,
    *,
    workspace_root_override: Path | None = None,
    env_file_override: str | Path | None = None,
):
    return load_qa_pipeline_config(
        config_path,
        workspace_root_override=workspace_root_override,
        env_file_override=env_file_override,
    )


def _run_pipeline_from_config(
    config_path: Path,
    parser: argparse.ArgumentParser,
    *,
    workspace_root_override: Path | None = None,
    env_file_override: str | Path | None = None,
) -> int:
    if not config_path.is_file():
        parser.error(
            f"Config file not found: {config_path}. "
            "Run 'qa-platform init-config' first or pass --config."
        )

    config = _load_config_from_path(
        config_path,
        workspace_root_override=workspace_root_override,
        env_file_override=env_file_override,
    )
    result = run_qa_pipeline(config)

    print("QA pipeline completed")
    print(f"Blocks: {result.extraction.imported_output_dir}")
    print(f"Run: {result.chapter.run_dir}")
    print(f"Report: {result.chapter.report_markdown_path}")
    print(f"Summary: {result.summary_path}")
    return 0


def _write_default_config(
    config_path: Path,
    *,
    workspace_root: Path,
    force: bool,
    parser: argparse.ArgumentParser,
) -> int:
    if config_path.exists() and not config_path.is_file():
        parser.error(f"Config path is not a file: {config_path}")

    if config_path.exists() and not force:
        parser.error(
            f"Config file already exists: {config_path}. "
            "Pass --force to overwrite."
        )

    for dirname in ("config", "input", "extracted_blocks", "run", "logs"):
        (workspace_root / dirname).mkdir(parents=True, exist_ok=True)

    env_path = workspace_root / ".env"
    if not env_path.exists():
        env_path.write_text("GEMINI_API_KEY=\n", encoding="utf-8")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_json = json.dumps(
        _default_config_payload(workspace_root),
        ensure_ascii=False,
        indent=2,
    )
    config_path.write_text(f"{config_json}\n", encoding="utf-8")
    print(f"Workspace: {workspace_root}")
    print(f"Config: {config_path}")
    print(f"Env: {env_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="qa-platform",
        description="Run QA orchestration pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run",
        help="Run QA orchestration pipeline.",
    )
    run_parser.add_argument(
        "--config",
        type=Path,
        default=None,
    )
    run_parser.add_argument("--workspace-root", default="")
    run_parser.add_argument("--env-file", default="")
    run_parser.set_defaults(
        handler=lambda args: _handle_run(args, run_parser)
    )

    init_parser = subparsers.add_parser(
        "init-config",
        help="Write a local QA pipeline config template.",
    )
    init_parser.add_argument(
        "--path",
        type=Path,
        default=None,
    )
    init_parser.add_argument("--workspace-root", default="")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(
        handler=lambda args: _handle_init_config(args, init_parser)
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check local QA platform dependencies.",
    )
    doctor_parser.add_argument("--workspace-root", default="")
    doctor_parser.add_argument("--config", default="")
    doctor_parser.add_argument("--docker-cmd", default="")
    doctor_parser.add_argument("--tesseract-cmd", default="")
    doctor_parser.add_argument("--resource-root", default="")
    doctor_parser.set_defaults(handler=_handle_doctor)

    return parser


def _handle_run(args, parser: argparse.ArgumentParser) -> int:
    workspace_root = resolve_workspace_root(args.workspace_root, config_dir=None)
    config_path = (
        Path(args.config).expanduser()
        if args.config
        else default_config_path(workspace_root)
    )
    return _run_pipeline_from_config(
        config_path,
        parser,
        workspace_root_override=workspace_root if args.workspace_root else None,
        env_file_override=args.env_file or None,
    )


def _handle_init_config(args, parser: argparse.ArgumentParser) -> int:
    workspace_root = resolve_workspace_root(args.workspace_root, config_dir=None)
    config_path = (
        Path(args.path).expanduser()
        if args.path
        else default_config_path(workspace_root)
    )
    return _write_default_config(
        config_path,
        workspace_root=workspace_root,
        force=args.force,
        parser=parser,
    )


def _handle_doctor(args) -> int:
    result = run_doctor(
        workspace_root=args.workspace_root or None,
        config_path=args.config or None,
        docker_cmd=args.docker_cmd or None,
        tesseract_cmd=args.tesseract_cmd or None,
        resource_root=args.resource_root or None,
    )
    print(format_doctor_result(result))
    return 0 if result.ok else 1


def _normalize_argv(argv: list[str]) -> list[str]:
    if argv and (argv[0] == "--config" or argv[0].startswith("--config=")):
        return ["run", *argv]
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        parser.print_help()
        return 2

    try:
        parsed_args = parser.parse_args(_normalize_argv(args))
        return parsed_args.handler(parsed_args)
    except _ParserExit as exc:
        return exc.status


if __name__ == "__main__":
    raise SystemExit(main())
