"""§5.1 audit_log 写入与任务钩子持久化单测（依赖 DB）。"""

import logging

import pytest

from apps.audit.models import AuditLog
from common.audit import record_audit
from common.tasks import SynTimeTask


class _AggTask(SynTimeTask):
    abstract = False
    audit_action = "aggregate"


@pytest.fixture
def task() -> SynTimeTask:
    instance = _AggTask()
    instance.name = "t.aggregate"
    return instance


@pytest.mark.django_db
def test_record_audit_persists_row():
    row = record_audit(
        "sync",
        operator="admin",
        role="成本管理员",
        params={"account_id": 1},
        result="success",
        cost_ms=42,
    )
    assert row is not None
    assert AuditLog.objects.count() == 1
    assert row.action == "sync"
    assert row.operator == "admin"
    assert row.params_snapshot == {"account_id": 1}
    assert row.result == "success"
    assert row.cost_ms == 42


@pytest.mark.django_db
def test_record_audit_truncates_large_params():
    row = record_audit("query", params="x" * 5000)
    assert row is not None
    assert isinstance(row.params_snapshot, str)
    assert len(row.params_snapshot) <= 2000


@pytest.mark.django_db
def test_record_audit_swallows_db_error(monkeypatch, caplog):
    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(AuditLog.objects, "create", _boom)
    with caplog.at_level(logging.ERROR):
        assert record_audit("sync", operator="x") is None
    assert "audit_log 写入失败" in caplog.text


@pytest.mark.django_db
def test_task_on_success_writes_audit(task):
    task.on_success(None, "task-id-1", (7,), {"operator": "admin"})
    row = AuditLog.objects.get()
    assert row.action == "aggregate"
    assert row.operator == "admin"
    assert row.result == "success"
    assert row.params_snapshot is not None
    assert row.params_snapshot["task"] == "t.aggregate"


@pytest.mark.django_db
def test_task_on_failure_writes_audit(task):
    task.on_failure(RuntimeError("boom"), "task-id-2", (), {}, None)
    row = AuditLog.objects.get()
    assert row.result == "failed"
    assert row.params_snapshot is not None
    assert "boom" in row.params_snapshot["error"]


@pytest.mark.django_db
def test_task_hook_system_operator_is_none(task):
    # 系统调度任务无 operator kwarg → operator 落 None
    task.on_success(None, "task-id-3", (), {})
    assert AuditLog.objects.get().operator is None
