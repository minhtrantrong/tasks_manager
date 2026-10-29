"""Acceptance test B: two concurrent workers never execute the same task."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

from task_manager import repository
from task_manager.db import Database
from task_manager.errors import LeaseConflict


def _worker(db_path: str, project_id: int, actor: str, queue) -> None:
    database = Database(Path(db_path))
    try:
        while True:
            task = repository.task_next(database, project_id)
            if task is None:
                break
            try:
                repository.task_start(database, task.id, actor=actor, lease_minutes=1)
            except LeaseConflict:
                continue
            repository.task_complete(
                database, task.id, actor=actor, outcome="done by " + actor
            )
        queue.put(("ok", actor))
    except BaseException as exc:  # pragma: no cover - surfaced by the assertion
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


def test_no_double_work(tmp_path):
    db_path = tmp_path / "acceptance_b.sqlite"
    db = Database(db_path)
    db.migrate()
    project = repository.project_upsert(db, "demo", "Demo")

    chain = [
        repository.task_add(db, project.id, f"Chain {index}", priority=2)
        for index in range(3)
    ]
    repository.task_link(db, chain[1].id, chain[0].id, "blocked_by")
    repository.task_link(db, chain[2].id, chain[1].id, "blocked_by")
    independent = [
        repository.task_add(db, project.id, f"Independent {index}", priority=1)
        for index in range(3)
    ]
    seeded_edges = repository.task_graph(db, project.id).edges

    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    actors = ["worker-a", "worker-b"]
    processes = [
        context.Process(target=_worker, args=(str(db_path), project.id, actor, queue))
        for actor in actors
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=120) for _ in processes]
    for process in processes:
        process.join(timeout=120)
        assert process.exitcode == 0

    assert all(result[0] == "ok" for result in results), results

    tasks = [*chain, *independent]
    for task in tasks:
        fetched = repository.task_get(db, task.id)
        assert fetched.status == "done"
        assert fetched.outcome in {f"done by {actor}" for actor in actors}
        assert fetched.outcome.count("done by") == 1

    graph = repository.task_graph(db, project.id)
    assert graph.edges == seeded_edges
    assert len(graph.edges) == 2
