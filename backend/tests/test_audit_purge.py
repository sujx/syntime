"""audit_log 保留期清理测试（engineering-conventions §7 / PRD 4.4-5：保留 12 个月）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.services import purge_audit_logs


def _log(created: datetime) -> AuditLog:
    row = AuditLog.objects.create(action=AuditLog.Action.QUERY, result="success")
    # auto_now_add 会覆盖构造值，故建好后强制回写 create_time
    AuditLog.objects.filter(pk=row.pk).update(create_time=created)
    return row


@pytest.mark.django_db
def test_purge_deletes_only_rows_before_cutoff():
    now = timezone.now()
    old = _log(now - timedelta(days=400))
    edge = _log(now - timedelta(days=365, hours=1))
    recent = _log(now - timedelta(days=10))

    cutoff = now - timedelta(days=365)
    deleted = purge_audit_logs(cutoff)

    assert deleted == 2
    remaining = set(AuditLog.objects.values_list("pk", flat=True))
    assert remaining == {recent.pk}
    assert old.pk not in remaining and edge.pk not in remaining


@pytest.mark.django_db
def test_purge_boundary_is_strictly_before():
    """create_time 恰好等于 cutoff 的行保留（< 而非 <=）。"""
    cutoff = datetime(2025, 9, 21, 0, 0, tzinfo=UTC)
    kept = _log(cutoff)
    gone = _log(cutoff - timedelta(seconds=1))
    deleted = purge_audit_logs(cutoff)
    assert deleted == 1
    assert AuditLog.objects.filter(pk=kept.pk).exists()
    assert not AuditLog.objects.filter(pk=gone.pk).exists()


@pytest.mark.django_db
def test_purge_no_rows_returns_zero():
    assert purge_audit_logs(timezone.now()) == 0
