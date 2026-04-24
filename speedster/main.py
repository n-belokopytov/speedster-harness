"""CLI entry point for the speedster orchestrator.

Commands:
  run [task_id]   - Process a task (or first pending task)
  list            - List all tasks with status
  status <id>     - Show detailed status for a task
  resume [task_id] - Resume a non-terminal task from last saved state
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import typer

from speedster.config import AgentConfig, default_config
from speedster.orchestrator import Orchestrator
from speedster.state_projection import StateProjection

app = typer(help="Speedster - Autonomous agent orchestrator")

logger = logging.getLogger("speedster")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _load_config() -> AgentConfig:
    prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
    return default_config(prompts_dir=prompts_dir)


@app.command()
def run(task_id: str | None = None, verbose: bool = False) -> None:
    """Process a task end-to-end (EM -> Engineer -> QA loop).

    If TASK_ID is provided, process that specific task.
    Otherwise, find the first pending task and process it.
    """

    _configure_logging(verbose)
    config = _load_config()
    orch = Orchestrator(config)
    asyncio.run(orch.run(task_id))


@app.command()
def resume(task_id: str | None = None, verbose: bool = False) -> None:
    """Resume a non-terminal task from its last saved state.

    Replays the event log to determine where each task left off,
    then continues from that point. If TASK_ID is provided,
    resume only that task. Otherwise, resume all non-terminal tasks.
    """

    _configure_logging(verbose)
    config = _load_config()
    orch = Orchestrator(config)
    projection = StateProjection(orch.event_log)

    if task_id:
        proj = projection.get_task(task_id)
        if not proj:
            typer.echo(f"Task {task_id} has no events in the log.", err=True)
            raise typer.Exit(1)
        if proj.is_terminal:
            typer.echo(f"Task {task_id} is terminal (phase: {proj.phase}).")
            raise typer.Exit(0)
        to_resume = [proj]
    else:
        to_resume = projection.get_non_terminal()
        if not to_resume:
            typer.echo("No non-terminal tasks to resume.")
            raise typer.Exit(0)

    for proj in to_resume:
        typer.echo(f"Resuming {proj.task_id} from phase={proj.phase}, next={proj.next_step()}")
        task = orch.task_manager.load_task(proj.task_id)
        step = proj.next_step()

        if step == "done":
            typer.echo(f"  {proj.task_id} is already at terminal state, skipping.")
            continue

        if step == "em":
            asyncio.run(orch.process_task(task))
        else:
            asyncio.run(orch.process_task(task))


@app.command()
def list_tasks(verbose: bool = False) -> None:
    """List all tasks with their current status."""

    _configure_logging(verbose)
    config = _load_config()
    orch = Orchestrator(config)

    tasks = orch.task_manager.list_tasks()
    projection = StateProjection(orch.event_log)
    projections = projection.rebuild()

    if not tasks:
        typer.echo("No tasks found.")
        return

    typer.echo(f"{'Task ID':<20} {'File Status':<12} {'Phase':<14} {'QA Rounds':<10} {'Last Event':<20}")
    typer.echo("-" * 76)

    for task in tasks:
        proj = projections.get(task.id)
        if proj:
            typer.echo(
                f"{task.id:<20} {task.status:<12} {proj.phase:<14} {proj.qa_rounds:<10} {proj.last_event_type:<20}"
            )
        else:
            typer.echo(f"{task.id:<20} {task.status:<12} {'pending':<14} {'0':<10} {'no events':<20}")


@app.command()
def status(task_id: str, verbose: bool = False) -> None:
    """Show detailed status for a specific task."""

    _configure_logging(verbose)
    config = _load_config()
    orch = Orchestrator(config)
    projection = StateProjection(orch.event_log)

    try:
        task = orch.task_manager.load_task(task_id)
    except FileNotFoundError:
        typer.echo(f"Task {task_id} not found in {config.task_dir}.", err=True)
        raise typer.Exit(1)

    proj = projection.get_task(task_id)

    typer.echo(f"Task: {task.id}")
    typer.echo(f"Description: {task.description}")
    typer.echo(f"Priority: {task.priority}")
    typer.echo(f"File Status: {task.status}")
    typer.echo(f"Has Breakdown: {task.has_breakdown}")

    if proj:
        typer.echo(f"Phase: {proj.phase}")
        typer.echo(f"Terminal: {proj.is_terminal}")
        typer.echo(f"QA Rounds: {proj.qa_rounds}")
        typer.echo(f"Last Event: {proj.last_event_type}")
        typer.echo(f"Last Message: {proj.last_event}")
        typer.echo(f"Next Step: {proj.next_step()}")
        typer.echo(f"Event History:")
        for i, et in enumerate(proj.event_types):
            typer.echo(f"  {i + 1}. {et}")
    else:
        typer.echo("Phase: pending (no events yet)")
        typer.echo("Next Step: em")

    events = orch.event_log.get_events_for_task(task_id)
    if events:
        typer.echo("\nFull Event Log:")
        for ev in events:
            typer.echo(f"  [{ev['seq']}] {ev['event_type']} (role={ev['role']}, model={ev['model']})")
            typer.echo(f"    {ev['message']}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
