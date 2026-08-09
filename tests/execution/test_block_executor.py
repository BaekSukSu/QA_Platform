from pathlib import Path

from qa_platform.execution.base import BlockExecutor
from qa_platform.execution.docker import DockerBlockExecutor
from qa_platform.contract.models import ExecutionResult


class FakeBlockExecutor:
    def execute(self, block_dir: Path) -> ExecutionResult:
        raise NotImplementedError


def test_structural_fake_satisfies_block_executor_protocol() -> None:
    assert isinstance(FakeBlockExecutor(), BlockExecutor)


def test_docker_executor_satisfies_block_executor_protocol() -> None:
    assert isinstance(DockerBlockExecutor(), BlockExecutor)
