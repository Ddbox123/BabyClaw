from core.runtime_manager.work_run_leases import (
    WorkRunLeaseRequest,
    check_lease_conflicts,
    infer_chat_turn_leases,
)


def test_readonly_chat_can_overlap_with_supervised_run():
    active = [
        {
            "runId": "supervised_1",
            "runKind": "supervised_evolution_run",
            "leases": ["evaluation"],
            "status": "running",
        }
    ]
    request = WorkRunLeaseRequest(run_kind="chat_turn", leases=["readonly_chat"])

    result = check_lease_conflicts(request, active)

    assert result.allowed is True
    assert result.conflicts == []


def test_coding_chat_conflicts_with_self_evolution_write_run():
    active = [
        {
            "runId": "self_1",
            "runKind": "self_evolution_run",
            "leases": ["evolution_transaction", "worktree_write", "memory_write"],
            "status": "running",
        }
    ]
    request = WorkRunLeaseRequest(run_kind="chat_turn", leases=["worktree_write"])

    result = check_lease_conflicts(request, active)

    assert result.allowed is False
    assert "worktree_write" in result.reason
    assert result.conflicts[0]["runId"] == "self_1"


def test_supervised_evaluation_conflicts_with_self_evolution_transaction():
    active = [
        {
            "runId": "self_1",
            "runKind": "self_evolution_run",
            "status": "running",
        }
    ]
    request = WorkRunLeaseRequest(run_kind="supervised_evolution_run", leases=["evaluation"])

    result = check_lease_conflicts(request, active)

    assert result.allowed is False
    assert "evaluation" in result.reason


def test_final_runs_and_unknown_leases_do_not_block_requests():
    active = [
        {
            "runId": "old_self",
            "runKind": "self_evolution_run",
            "leases": ["worktree_write"],
            "status": "done",
        },
        {
            "runId": "legacy",
            "runKind": "legacy",
            "leases": ["future_observer"],
            "status": "running",
        },
    ]
    request = WorkRunLeaseRequest(run_kind="chat_turn", leases=["worktree_write"])

    result = check_lease_conflicts(request, active)

    assert result.allowed is True


def test_infer_chat_turn_leases_defaults_to_readonly_and_marks_write_intent():
    assert infer_chat_turn_leases({"content": "解释当前状态"}) == ["readonly_chat"]
    assert infer_chat_turn_leases({"mode": "coding", "content": "修改这个 bug"}) == ["worktree_write", "memory_write"]
    assert infer_chat_turn_leases({"writeIntent": True}) == ["worktree_write", "memory_write"]
    assert infer_chat_turn_leases({"content": "继续修复这个 bug"}) == ["worktree_write", "memory_write"]
    assert infer_chat_turn_leases({"content": "继续", "activeTask": {"status": "editing"}}) == [
        "worktree_write",
        "memory_write",
    ]
