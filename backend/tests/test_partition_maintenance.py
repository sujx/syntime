"""分区维护测试（engineering-conventions §7 / PRD 4.4-5）。

cloud_bill_detail 按 bill_date 月分区、DEFAULT 兜底。维护任务：预建未来分区 +
DETACH（非 DROP，脱离父表保留为独立归档表）超 24 个月的旧分区 + 清理 audit_log。
DDL 在 PostgreSQL 中可事务化，django_db 回滚即清理，测试间互不残留。
"""

from __future__ import annotations

from datetime import date

import pytest
from django.db import connection

from apps.billing.partitions import (
    detach_partitions_before,
    ensure_future_partitions,
    ensure_monthly_partition,
    list_bill_partitions,
    partition_name,
    retention_cutoff,
)


def _regclass(name: str) -> bool:
    """表/分区物理是否存在（to_regclass 非空）。"""
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", [name])
        return bool(cur.fetchone()[0])


def _is_attached(name: str) -> bool:
    """是否仍是 cloud_bill_detail 的子分区（pg_inherits 中）。"""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_inherits i "
            "JOIN pg_class c ON c.oid=i.inhrelid "
            "JOIN pg_class p ON p.oid=i.inhparent "
            "WHERE p.relname='cloud_bill_detail' AND c.relname=%s",
            [name],
        )
        return cur.fetchone()[0] > 0


# ---------- ensure_monthly_partition ----------


@pytest.mark.django_db
def test_ensure_monthly_partition_creates_then_idempotent():
    assert ensure_monthly_partition(2026, 9) is True
    assert _regclass("cloud_bill_detail_2026_09")
    assert _is_attached("cloud_bill_detail_2026_09")
    # 再建同月：已存在 → False，不报错
    assert ensure_monthly_partition(2026, 9) is False


@pytest.mark.django_db
def test_partition_name_zero_pads():
    assert partition_name(2026, 9) == "cloud_bill_detail_2026_09"
    assert partition_name(2026, 12) == "cloud_bill_detail_2026_12"


# ---------- ensure_future_partitions（含跨年）----------


@pytest.mark.django_db
def test_ensure_future_partitions_current_plus_two():
    created = ensure_future_partitions(date(2026, 9, 21), months_ahead=2)
    assert created == [
        "cloud_bill_detail_2026_09",
        "cloud_bill_detail_2026_10",
        "cloud_bill_detail_2026_11",
    ]
    # 幂等：窗口内均已存在 → 不再新建
    assert ensure_future_partitions(date(2026, 9, 21), months_ahead=2) == []


@pytest.mark.django_db
def test_ensure_future_partitions_rolls_over_year():
    created = ensure_future_partitions(date(2026, 12, 15), months_ahead=2)
    assert created == [
        "cloud_bill_detail_2026_12",
        "cloud_bill_detail_2027_01",
        "cloud_bill_detail_2027_02",
    ]


# ---------- list_bill_partitions ----------


@pytest.mark.django_db
def test_list_excludes_default_and_sorts():
    ensure_monthly_partition(2026, 11)
    ensure_monthly_partition(2026, 9)
    ensure_monthly_partition(2026, 10)
    assert list_bill_partitions() == [
        "cloud_bill_detail_2026_09",
        "cloud_bill_detail_2026_10",
        "cloud_bill_detail_2026_11",
    ]
    assert "cloud_bill_detail_default" not in list_bill_partitions()


# ---------- retention_cutoff ----------


def test_retention_cutoff_keeps_n_months_inclusive():
    # 保留 24 个月（含当月 2026-09）→ 最早保留 2024-10，cutoff=2024-10-01
    assert retention_cutoff(date(2026, 9, 21), 24) == date(2024, 10, 1)


# ---------- detach_partitions_before ----------


@pytest.mark.django_db
def test_detach_only_partitions_before_cutoff():
    for ym in [(2024, 8), (2024, 9), (2024, 10), (2026, 9)]:
        ensure_monthly_partition(*ym)
    detached = detach_partitions_before(date(2024, 10, 1))
    assert detached == ["cloud_bill_detail_2024_08", "cloud_bill_detail_2024_09"]
    # 已脱离父表但物理表仍在（归档，非 DROP）
    assert not _is_attached("cloud_bill_detail_2024_08")
    assert _regclass("cloud_bill_detail_2024_08")
    # cutoff 当月及以后保留为分区
    assert _is_attached("cloud_bill_detail_2024_10")
    assert _is_attached("cloud_bill_detail_2026_09")


@pytest.mark.django_db
def test_detach_never_touches_default_and_is_idempotent():
    ensure_monthly_partition(2024, 1)
    assert detach_partitions_before(date(2024, 2, 1)) == ["cloud_bill_detail_2024_01"]
    # 再跑一次：已不在分区列表 → 不重复 DETACH（否则会报错）
    assert detach_partitions_before(date(2024, 2, 1)) == []
    # DEFAULT 分区始终挂载
    assert _is_attached("cloud_bill_detail_default")
