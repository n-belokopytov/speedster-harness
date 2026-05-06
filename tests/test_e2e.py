"""End-to-end integration tests with real HTTP agent servers.

Spins up FastAPI agent servers in mock mode and runs the orchestrator
through the full EM -> Engineer -> QA loop over real HTTP.
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

import httpx
import pytest
import uvicorn

from agent.config import AgentConfig as AgentServerConfig
from agent.server import AgentServer
from speedster.config import (
    AgentConfig,
    ConnectivityConfig,
    EventLogConfig,
    StorageConfig,
)
from speedster.orchestrator import Orchestrator
from speedster.task_manager import Task


def _opencode_on_path() -> bool:
    """Check if opencode CLI is reachable via subprocess."""

    import subprocess as sp

    try:
        result = sp.run(
            ["opencode", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, sp.TimeoutExpired):
        return False


def _get_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_agent(role: str, port: int, ready_event: threading.Event, mock_mode: bool = True, repo_root: str | None = None) -> tuple[AgentServer, threading.Thread]:
    """Start an agent server in a background thread."""

    kwargs = {
        "role": role,
        "model": f"vllm/{role}-e2e",
        "host": "127.0.0.1",
        "port": port,
        "mock_mode": mock_mode,
    }
    if repo_root is not None:
        kwargs["repo_root"] = repo_root

    config = AgentServerConfig(**kwargs)
    server = AgentServer(config)

    def run():
        ready_event.set()
        uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server: AgentServer) -> None:
    pass


@pytest.fixture(scope="module")
def agent_servers():
    """Start three agent servers (EM, Engineer, QA) on ephemeral ports."""

    import time

    em_port = _get_free_port()
    eng_port = _get_free_port()
    qa_port = _get_free_port()

    em_ready = threading.Event()
    eng_ready = threading.Event()
    qa_ready = threading.Event()

    em_server, em_thread = _start_agent("em", em_port, em_ready)
    eng_server, eng_thread = _start_agent("engineer", eng_port, eng_ready)
    qa_server, qa_thread = _start_agent("qa", qa_port, qa_ready)

    em_ready.wait(timeout=5)
    eng_ready.wait(timeout=5)
    qa_ready.wait(timeout=5)

    time.sleep(0.5)

    yield {
        "em": f"http://127.0.0.1:{em_port}",
        "engineer": f"http://127.0.0.1:{eng_port}",
        "qa": f"http://127.0.0.1:{qa_port}",
    }


@pytest.fixture(scope="module")
def real_agent_servers():
    """Start three agent servers in non-mock mode (real ACP).

    Requires the opencode CLI and a reachable model endpoint.
    """

    import time

    em_port = _get_free_port()
    eng_port = _get_free_port()
    qa_port = _get_free_port()

    em_ready = threading.Event()
    eng_ready = threading.Event()
    qa_ready = threading.Event()

    import tempfile
    import os

    tmp_workspace = tempfile.mkdtemp()
    em_server, em_thread = _start_agent("em", em_port, em_ready, mock_mode=False, repo_root=tmp_workspace)
    eng_server, eng_thread = _start_agent("engineer", eng_port, eng_ready, mock_mode=False, repo_root=tmp_workspace)
    qa_server, qa_thread = _start_agent("qa", qa_port, qa_ready, mock_mode=False, repo_root=tmp_workspace)

    em_ready.wait(timeout=5)
    eng_ready.wait(timeout=5)
    qa_ready.wait(timeout=5)

    time.sleep(0.5)

    yield {
        "em": f"http://127.0.0.1:{em_port}",
        "engineer": f"http://127.0.0.1:{eng_port}",
        "qa": f"http://127.0.0.1:{qa_port}",
    }


def _make_valid_breakdown() -> dict:
    return {
        "id": "task-e2e",
        "description": "E2E test task",
        "acceptance_criteria": {
            "functional": ["Endpoint returns 200"],
            "solid": "The implementation adheres to SOLID principles by separating concerns.",
            "yagni_kiss": "The implementation adheres to YAGNI and KISS by keeping it simple.",
            "testing": "Well-designed unit tests cover the behavior, with minimum unit test coverage of 80%+ for touched modules.",
        },
        "context_files": ["src/test.py"],
        "context_rationale": "Test file needs changes",
        "depends_on": [],
        "estimated_context_tokens": 500,
        "estimated_work_tokens": 2000,
        "complexity_level": "simple",
        "target_model_class": "mid-size-25B",
        "status": "pending",
        "qa_rounds": 0,
        "feedback": None,
        "tasks": [],
    }


def _make_valid_engineer_output() -> dict:
    return {
        "task_id": "task-e2e",
        "status": "implemented",
        "branch": "speedster/task-e2e",
        "files_changed": ["src/test.py"],
        "tests_added_or_updated": ["tests/test_test.py"],
        "acceptance_evidence": {
            "functional": [{"criterion": "Endpoint returns 200", "evidence": "Test passes"}],
            "solid": "Separation maintained",
            "yagni_kiss": "Simple solution",
            "testing": "Unit tests added",
        },
        "assumptions": [],
        "notes": "",
        "blocked_reason": "",
        "requested_context": [],
    }


def _make_qa_approved() -> dict:
    return {
        "task_id": "task-e2e",
        "status": "approved",
        "branch": "speedster/task-e2e",
        "commit": "abc123def456",
        "round": 1,
        "findings": {
            "functional": [{"criterion": "Endpoint returns 200", "verdict": "met", "evidence": "Verified"}],
            "solid": {"verdict": "met", "evidence": "Good"},
            "yagni_kiss": {"verdict": "met", "evidence": "Good"},
            "testing": {"verdict": "met", "evidence": "Good"},
        },
        "rejection_reasons": [],
        "notes": "",
    }


def _make_qa_rejected() -> dict:
    return {
        "task_id": "task-e2e",
        "status": "rejected",
        "branch": "speedster/task-e2e",
        "commit": "abc123def456",
        "round": 1,
        "findings": {
            "functional": [{"criterion": "Endpoint returns 200", "verdict": "unmet", "evidence": "Missing error handling"}],
            "solid": {"verdict": "met", "evidence": "Good"},
            "yagni_kiss": {"verdict": "met", "evidence": "Good"},
            "testing": {"verdict": "met", "evidence": "Good"},
        },
        "rejection_reasons": ["Missing error handling"],
        "notes": "",
    }


class TestE2EHTTP:
    """Integration tests that hit real HTTP agent servers."""

    def test_health_check(self, agent_servers: dict[str, str]) -> None:
        """Verify all agent servers respond to health checks."""

        with httpx.Client(timeout=5.0) as client:
            for role, url in agent_servers.items():
                resp = client.get(f"{url}/health")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "healthy"

    def test_work_endpoint_em(self, agent_servers: dict[str, str]) -> None:
        """Verify EM agent returns valid breakdown."""

        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{agent_servers['em']}/work",
                json={
                    "task_id": "task-e2e",
                    "description": "Produce a plan for task-e2e",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "output" in data
            output = json.loads(data["output"])
            assert "id" in output

    def test_work_endpoint_engineer(self, agent_servers: dict[str, str]) -> None:
        """Verify Engineer agent returns valid output."""

        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{agent_servers['engineer']}/work",
                json={
                    "task_id": "task-e2e",
                    "description": "Implement task-e2e",
                    "plan": "{}",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            output = json.loads(data["output"])
            assert output["status"] == "implemented"

    def test_work_endpoint_qa(self, agent_servers: dict[str, str]) -> None:
        """Verify QA agent returns valid review."""

        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{agent_servers['qa']}/work",
                json={
                    "task_id": "task-e2e",
                    "description": "Review task-e2e",
                    "plan": "{}",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            output = json.loads(data["output"])
            assert output["status"] == "approved"

    @pytest.mark.asyncio
    async def test_full_loop_approve(
        self, agent_servers: dict[str, str], tmp_path: Path
    ) -> None:
        """Full EM -> Engineer -> QA approve path over real HTTP."""

        event_log_path = tmp_path / "events.csv"
        task_dir = tmp_path / "tasks" / "task-e2e"
        task_dir.mkdir(parents=True)

        (task_dir / "task.json").write_text(
            json.dumps({
                "id": "task-e2e",
                "description": "E2E test task",
                "priority": "high",
                "status": "pending",
            })
        )

        config = AgentConfig(
            connectivity=ConnectivityConfig(
                em_url=agent_servers["em"],
                eng_url=agent_servers["engineer"],
                qa_url=agent_servers["qa"],
            ),
            storage=StorageConfig(
                event_log=EventLogConfig(path=event_log_path),
                task_dir=tmp_path / "tasks",
            ),
            max_qa_rounds=3,
        )

        orch = Orchestrator(config)
        task = orch.task_manager.load_task("task-e2e")
        await orch.process_task(task)

        events = list(orch.event_log.replay())
        event_types = [e["event_type"] for e in events]

        assert "TaskCreated" in event_types
        assert "PlanningCompleted" in event_types
        assert "ImplementationCompleted" in event_types
        assert "ReviewPassed" in event_types
        assert "TaskCompleted" in event_types

        models_used = [e["model"] for e in events if e["model"]]
        assert "vllm/em-e2e" in models_used
        assert "vllm/engineer-e2e" in models_used
        assert "vllm/qa-e2e" in models_used

    @pytest.mark.asyncio
    async def test_full_loop_reject_then_approve(
        self, agent_servers: dict[str, str], tmp_path: Path
    ) -> None:
        """QA rejects, Engineer re-runs, QA approves -- over real HTTP.

        Note: Agent servers in mock mode always return the same response,
        so QA will approve on first try. This test verifies the happy path
        with real HTTP transport. The reject->approve path is covered by
        unit tests with mocked agents.
        """

        event_log_path = tmp_path / "events.csv"
        task_dir = tmp_path / "tasks" / "task-e2e-retry"
        task_dir.mkdir(parents=True)

        (task_dir / "task.json").write_text(
            json.dumps({
                "id": "task-e2e-retry",
                "description": "E2E retry test",
                "priority": "medium",
                "status": "pending",
            })
        )

        config = AgentConfig(
            connectivity=ConnectivityConfig(
                em_url=agent_servers["em"],
                eng_url=agent_servers["engineer"],
                qa_url=agent_servers["qa"],
            ),
            storage=StorageConfig(
                event_log=EventLogConfig(path=event_log_path),
                task_dir=tmp_path / "tasks",
            ),
            max_qa_rounds=3,
        )

        orch = Orchestrator(config)
        task = orch.task_manager.load_task("task-e2e-retry")
        await orch.process_task(task)

        events = list(orch.event_log.replay())
        event_types = [e["event_type"] for e in events]

        assert "TaskCompleted" in event_types
        assert "TaskFailed" not in event_types

        last_event = events[-1]
        assert last_event["event_type"] == "TaskCompleted"


def _assert_loop_complete(events: list[dict]) -> None:
    """Reusable assertion that a full loop completed successfully."""

    event_types = [e["event_type"] for e in events]

    assert "TaskCreated" in event_types
    assert "PlanningCompleted" in event_types
    assert "ImplementationCompleted" in event_types
    assert "ReviewPassed" in event_types
    assert "TaskCompleted" in event_types


@pytest.mark.skipif(
    not _opencode_on_path(),
    reason="opencode CLI not reachable via subprocess",
)
@pytest.mark.xfail(
    reason="Requires opencode CLI with --stdin ACP support and a reachable model endpoint",
    strict=False,
)
class TestE2ERealModel:
    """Integration tests with real OpenCode ACP (non-mock mode).

    These tests require a reachable model endpoint configured via
    the MODEL environment variable and opencode CLI installed.
    """

    @pytest.mark.asyncio
    async def test_full_loop_real_model_approve(
        self, real_agent_servers: dict[str, str], tmp_path: Path
    ) -> None:
        """Full loop completes with agent servers and all expected events."""

        event_log_path = tmp_path / "events.csv"
        task_dir = tmp_path / "tasks" / "task-e2e-real"
        task_dir.mkdir(parents=True)

        (task_dir / "task.json").write_text(
            json.dumps({
                "id": "task-e2e-real",
                "description": "E2E real model test task",
                "priority": "high",
                "status": "pending",
            })
        )

        config = AgentConfig(
            connectivity=ConnectivityConfig(
                em_url=agent_servers["em"],
                eng_url=agent_servers["engineer"],
                qa_url=agent_servers["qa"],
            ),
            storage=StorageConfig(
                event_log=EventLogConfig(path=event_log_path),
                task_dir=tmp_path / "tasks",
            ),
            max_qa_rounds=3,
        )

        orch = Orchestrator(config)
        task = orch.task_manager.load_task("task-e2e-real")
        await orch.process_task(task)

        events = list(orch.event_log.replay())
        _assert_loop_complete(events)

        models_used = [e["model"] for e in events if e["model"]]
        assert "vllm/em-e2e" in models_used
        assert "vllm/engineer-e2e" in models_used
        assert "vllm/qa-e2e" in models_used

    @pytest.mark.asyncio
    async def test_reproducibility_two_consecutive_runs(
        self, real_agent_servers: dict[str, str], tmp_path: Path
    ) -> None:
        """Two consecutive full-loop runs both reach TaskCompleted."""

        async def run_once(task_id: str, event_log_path: Path) -> list[dict]:
            """Execute a single full EM -> Engineer -> QA loop."""

            task_dir = tmp_path / "tasks" / task_id
            task_dir.mkdir(parents=True, exist_ok=True)

            (task_dir / "task.json").write_text(
                json.dumps({
                    "id": task_id,
                    "description": "Reproducibility test task",
                    "priority": "high",
                    "status": "pending",
                })
      )

            config = AgentConfig(
                connectivity=ConnectivityConfig(
                    em_url=real_agent_servers["em"],
                    eng_url=real_agent_servers["engineer"],
                    qa_url=real_agent_servers["qa"],
                ),
                storage=StorageConfig(
                    event_log=EventLogConfig(path=event_log_path),
                    task_dir=tmp_path / "tasks",
                ),
                max_qa_rounds=3,
            )

            orch = Orchestrator(config)
            task = orch.task_manager.load_task(task_id)
            await orch.process_task(task)

            return list(orch.event_log.replay())

        run1_events = await run_once(
            "task-repro-1",
            tmp_path / "events1.csv",
        )
        run2_events = await run_once(
            "task-repro-2",
            tmp_path / "events2.csv",
        )

        _assert_loop_complete(run1_events)
        _assert_loop_complete(run2_events)

        run1_models = [e["model"] for e in run1_events if e["model"]]
        run2_models = [e["model"] for e in run2_events if e["model"]]

        assert set(run1_models) == set(run2_models)
        assert "vllm/em-e2e" in run1_models
        assert "vllm/engineer-e2e" in run1_models
        assert "vllm/qa-e2e" in run1_models
