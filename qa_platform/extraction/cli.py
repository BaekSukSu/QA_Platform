from __future__ import annotations

import argparse
import json
from pathlib import Path

from qa_platform.extraction.config import load_document_extraction_config
from qa_platform.extraction.pipeline import run_document_extraction_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run document extraction pipeline.")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)

    raw_config = json.loads(args.config.read_text(encoding="utf-8"))
    config = load_document_extraction_config(
        raw_config,
        config_dir=args.config.parent,
    )
    result = run_document_extraction_pipeline(config)
    print(f"Imported {len(result.block_files)} blocks into {result.imported_output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
