"""Tests for typed relations, cycle rejection, and the graph view."""

from __future__ import annotations

import threading

import pytest

from task_manager import repository
from task_manager.db import Database
from task_manager.errors import CycleDetected, NotFound, ValidationError


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


@pytest.fixture()
def project(db):
    return repository.project_upsert(db, "demo", "Demo")


def test_link_unlink_round_trip(db, project):
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    relation = repository.task_link(db, first.id, second.id, "blocked_by")
    assert relation.task_id == first.id
    assert relation.related_id == second.id
    detail = repository.task_get(db, first.id)
    assert any(rel.related_id == second.id for rel in detail.relations)
    repository.task_unlink(db, first.id, second.id, "blocked_by")
    detail = repository.task_get(db, first.id)
    assert detail.relations == []


def test_self_link_rejected(db, project):
    task = repository.task_add(db, project.id, "A")
    with pytest.raises(ValidationError):
        repository.task_link(db, task.id, task.id, "blocked_by")


def test_cross_project_link_rejected(db, project):
    other = repository.project_upsert(db, "other", "Other")
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, other.id, "B")
    with pytest.raises(ValidationError):
        repository.task_link(db, first.id, second.id, "blocked_by")


def test_direct_two_cycle_rejected(db, project):
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    repository.task_link(db, first.id, second.id, "blocked_by")
    with pytest.raises(CycleDetected):
        repository.task_link(db, second.id, first.id, "blocked_by")


def test_transitive_cycle_rejected(db, project):
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    third = repository.task_add(db, project.id, "C")
    repository.task_link(db, first.id, second.id, "blocked_by")
    repository.task_link(db, second.id, third.id, "blocked_by")
    with pytest.raises(CycleDetected):
        repository.task_link(db, third.id, first.id, "blocked_by")


def test_diamond_is_legal(db, project):
    a = repository.task_add(db, project.id, "A")
    b = repository.task_add(db, project.id, "B")
    c = repository.task_add(db, project.id, "C")
    d = repository.task_add(db, project.id, "D")
    repository.task_link(db, b.id, a.id, "blocked_by")
    repository.task_link(db, c.id, a.id, "blocked_by")
    repository.task_link(db, d.id, b.id, "blocked_by")
    repository.task_link(db, d.id, c.id, "blocked_by")
    graph = repository.task_graph(db, project.id)
    assert len(graph.edges) == 4


def test_provenance_kinds_do_not_cycle_check(db, project):
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    repository.task_link(db, first.id, second.id, "related")
    repository.task_link(db, second.id, first.id, "related")
    repository.task_link(db, first.id, second.id, "discovered_during")
    graph = repository.task_graph(db, project.id)
    assert len(graph.edges) == 3


def test_duplicates_rejected_but_other_kind_allowed(db, project):
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    repository.task_link(db, first.id, second.id, "related")
    with pytest.raises(ValidationError):
        repository.task_link(db, first.id, second.id, "related")
    repository.task_link(db, first.id, second.id, "discovered_during")
    assert len(repository.task_graph(db, project.id).edges) == 2


def test_task_graph_nodes_edges_and_waiting(db, project):
    first = repository.task_add(db, project.id, "A", priority=1)
    second = repository.task_add(db, project.id, "B", priority=2)
    third = repository.task_add(db, project.id, "C", priority=3)
    repository.task_link(db, first.id, second.id, "blocked_by")
    repository.task_delete(db, third.id)
    graph = repository.task_graph(db, project.id)
    assert [node.id for node in graph.nodes] == [first.id, second.id, third.id]
    assert [(edge.from_id, edge.to_id, edge.kind) for edge in graph.edges] == [
        (first.id, second.id, "blocked_by")
    ]
    assert graph.waiting == []
    assert graph.nodes[-1].status == "cancelled"


def test_unlink_missing_edge_ok_and_missing_task_not_found(db, project):
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    assert repository.task_unlink(db, first.id, second.id, "related") is None
    with pytest.raises(NotFound):
        repository.task_unlink(db, 999, second.id, "related")
    with pytest.raises(NotFound):
        repository.task_link(db, 999, second.id, "related")


def test_concurrent_opposite_links_never_form_cycle(tmp_path):
    db_path = tmp_path / "race.sqlite"
    setup = Database(db_path)
    setup.migrate()
    project = repository.project_upsert(setup, "demo", "Demo")
    first = repository.task_add(setup, project.id, "A")
    second = repository.task_add(setup, project.id, "B")

    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def worker(source: int, target: int) -> None:
        database = Database(db_path)
        barrier.wait()
        try:
            repository.task_link(database, source, target, "blocked_by")
            outcome = "ok"
        except CycleDetected:
            outcome = "cycle"
        with lock:
            results.append(outcome)

    threads = [
        threading.Thread(target=worker, args=(first.id, second.id)),
        threading.Thread(target=worker, args=(second.id, first.id)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["cycle", "ok"]
    graph = repository.task_graph(setup, project.id)
    pairs = {(edge.from_id, edge.to_id) for edge in graph.edges}
    assert not ({(first.id, second.id), (second.id, first.id)} <= pairs)
