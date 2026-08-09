from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from qa_platform.contract.models import ExecutionResult


@runtime_checkable
class BlockExecutor(Protocol):
    def execute(self, block_dir: Path) -> ExecutionResult:
        ...
