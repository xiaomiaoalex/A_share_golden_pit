from src.execution import DurableOrchestrator


def test_dag_dependencies_unlock_only_after_success(tmp_path):
    orchestrator = DurableOrchestrator(tmp_path / "dag.db")
    orchestrator.migrate()
    workflow_id = orchestrator.create_workflow(
        "research",
        [
            {"node_id": "dataset", "node_type": "BUILD_DATASET", "payload": {}},
            {"node_id": "research", "node_type": "RUN_MODEL", "dependencies": ["dataset"], "payload": {}},
            {"node_id": "validate", "node_type": "VALIDATE", "dependencies": ["research"], "payload": {}},
        ],
        metadata={"snapshot_id": "snapshot-1"},
    )

    assert orchestrator.claim_ready(workflow_id)["node_id"] == "dataset"
    assert orchestrator.claim_ready(workflow_id) is None
    orchestrator.complete(workflow_id, "dataset", {"dataset_id": "d1"})
    assert orchestrator.claim_ready(workflow_id)["node_id"] == "research"
    orchestrator.complete(workflow_id, "research", {"report": "draft"})
    assert orchestrator.claim_ready(workflow_id)["node_id"] == "validate"
    orchestrator.complete(workflow_id, "validate", {"valid": True})
    assert orchestrator.claim_ready(workflow_id) is None


def test_retry_budget_exhaustion_moves_node_to_dead_letter(tmp_path):
    orchestrator = DurableOrchestrator(tmp_path / "dead-letter.db")
    orchestrator.migrate()
    workflow_id = orchestrator.create_workflow(
        "provider-call",
        [{"node_id": "call", "node_type": "PROVIDER", "retry_budget": 1, "payload": {}}],
    )
    orchestrator.claim_ready(workflow_id)
    orchestrator.fail(workflow_id, "call", "TRANSIENT_PROVIDER_ERROR", "first")
    assert orchestrator.node(workflow_id, "call")["status"] == "READY"
    orchestrator.claim_ready(workflow_id)
    orchestrator.fail(workflow_id, "call", "TRANSIENT_PROVIDER_ERROR", "second")
    assert orchestrator.node(workflow_id, "call")["status"] == "DEAD_LETTER"


def test_circuit_breaker_opens_at_failure_threshold(tmp_path):
    orchestrator = DurableOrchestrator(tmp_path / "breaker.db")
    orchestrator.migrate()

    assert orchestrator.record_resource_failure("deepseek", threshold=3) == "CLOSED"
    assert orchestrator.record_resource_failure("deepseek", threshold=3) == "CLOSED"
    assert orchestrator.record_resource_failure("deepseek", threshold=3) == "OPEN"


def test_node_names_are_scoped_to_workflow_and_cycles_are_rejected(tmp_path):
    orchestrator = DurableOrchestrator(tmp_path / "scope.db")
    orchestrator.migrate()
    first = orchestrator.create_workflow(
        "first", [{"node_id": "shared", "node_type": "TASK"}]
    )
    second = orchestrator.create_workflow(
        "second", [{"node_id": "shared", "node_type": "TASK"}]
    )
    assert orchestrator.claim_ready(first)["node_id"] == "shared"
    assert orchestrator.claim_ready(second)["node_id"] == "shared"

    import pytest

    with pytest.raises(ValueError, match="环"):
        orchestrator.create_workflow(
            "cyclic",
            [
                {"node_id": "a", "node_type": "TASK", "dependencies": ["b"]},
                {"node_id": "b", "node_type": "TASK", "dependencies": ["a"]},
            ],
        )


def test_pause_resume_and_cancel_gate_claims(tmp_path):
    orchestrator = DurableOrchestrator(tmp_path / "control.db")
    orchestrator.migrate()
    workflow_id = orchestrator.create_workflow(
        "controlled", [{"node_id": "task", "node_type": "TASK"}]
    )
    orchestrator.pause(workflow_id)
    assert orchestrator.claim_ready(workflow_id) is None
    orchestrator.resume(workflow_id)
    assert orchestrator.claim_ready(workflow_id)["status"] == "RUNNING"
    orchestrator.cancel(workflow_id)
    assert orchestrator.node(workflow_id, "task")["status"] == "CANCELLED"
