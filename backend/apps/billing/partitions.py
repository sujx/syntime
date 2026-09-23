"""cloud_bill_detail 月度分区维护（engineering-conventions §7 / PRD 4.4-5）。

``cloud_bill_detail`` 按 ``bill_date`` RANGE 分区、``cloud_bill_detail_default`` 兜底。
本模块用原生 DDL 做两件事，供每月 beat 任务调用：

- **预建**当月 + 未来 N 个月的分区（避免账单落入 DEFAULT 兜底分区，影响裁剪与归档）；
- **归档**超过在线保留期（24 个月）的旧分区——按用户拍板用 ``DETACH``（脱离父表，
  保留为独立物理表以便后续 dump/清理），**不 DROP**（不丢历史账单）。

分区命名 ``cloud_bill_detail_YYYY_MM``，月份零填充，故按名排序即按时间排序。
表名全部由整型年/月格式化而来，不含外部输入，无注入面。
DDL 在 PostgreSQL 中可事务化：调用方（任务）失败回滚即撤销本次分区变更。
"""

from __future__ import annotations

import logging
from datetime import date

from django.db import connection

logger = logging.getLogger(__name__)

_PARENT = "cloud_bill_detail"
_DEFAULT_PARTITION = "cloud_bill_detail_default"
# 在线保留月数（PRD 4.4-5：cloud_bill_detail 在线保留 24 个月，超期归档）
BILL_RETENTION_MONTHS = 24
# 预建未来月数（§7：预建未来 2 个月分区）
PRECREATE_MONTHS_AHEAD = 2


def partition_name(year: int, month: int) -> str:
    """月分区表名（零填充，按名排序 == 按时间排序）。"""
    return f"{_PARENT}_{year:04d}_{month:02d}"


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """``[当月首日, 次月首日)`` 的 RANGE 边界。"""
    ny, nm = _add_months(year, month, 1)
    return date(year, month, 1), date(ny, nm, 1)


def _exists(name: str) -> bool:
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", [name])
        return bool(cur.fetchone()[0])


def ensure_monthly_partition(year: int, month: int) -> bool:
    """幂等预建某月分区；新建返回 True，已存在返回 False。"""
    name = partition_name(year, month)
    if _exists(name):
        return False
    start, end = _month_bounds(year, month)
    with connection.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {name} PARTITION OF {_PARENT} "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )
    logger.info("预建账单分区 %s [%s, %s)", name, start, end)
    return True


def ensure_future_partitions(today: date, months_ahead: int = PRECREATE_MONTHS_AHEAD) -> list[str]:
    """预建当月 + 未来 ``months_ahead`` 个月分区，返回本次新建的分区名（按时间序）。"""
    created: list[str] = []
    for delta in range(months_ahead + 1):
        year, month = _add_months(today.year, today.month, delta)
        if ensure_monthly_partition(year, month):
            created.append(partition_name(year, month))
    return created


def list_bill_partitions() -> list[str]:
    """当前挂在父表下的月分区名（排除 DEFAULT 兜底分区），按名（即按时间）升序。"""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT c.relname FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "WHERE p.relname = %s AND c.relname ~ %s "
            "ORDER BY c.relname",
            [_PARENT, rf"^{_PARENT}_[0-9]{{4}}_[0-9]{{2}}$"],
        )
        return [row[0] for row in cur.fetchall()]


def retention_cutoff(today: date, months: int = BILL_RETENTION_MONTHS) -> date:
    """在线保留 ``months`` 个月（含当月）时，最早保留月的首日；早于此的分区应归档。"""
    year, month = _add_months(today.year, today.month, -(months - 1))
    return date(year, month, 1)


def detach_partitions_before(cutoff: date) -> list[str]:
    """DETACH 起始月早于 ``cutoff`` 的月分区（脱离父表、保留物理表归档），返回被脱离的分区名。

    幂等：已 DETACH 的表不再出现在 ``list_bill_partitions()``，故重复调用不重复 DETACH。
    DEFAULT 兜底分区不参与（命名不匹配月分区正则）。
    """
    detached: list[str] = []
    cutoff_ym = (cutoff.year, cutoff.month)
    for name in list_bill_partitions():
        # 名称形如 cloud_bill_detail_YYYY_MM，取末两段解析年月
        year_str, month_str = name.rsplit("_", 2)[1:]
        year, month = int(year_str), int(month_str)
        if (year, month) < cutoff_ym:
            with connection.cursor() as cur:
                cur.execute(f"ALTER TABLE {_PARENT} DETACH PARTITION {name}")
            logger.info(
                "归档账单分区（DETACH）%s，起始月 %04d-%02d 早于 %s", name, year, month, cutoff
            )
            detached.append(name)
    return detached
