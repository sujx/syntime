"""账单导入与同步窗口服务（engineering-conventions §6 幂等：uk_bill / uk_sync_window）。

- ``claim_sync_window`` / ``release_sync_window``：同账号同账期同触发方式仅一条
  ``sync_log``（uk_sync_window）。运行中重复触发抛 ``SyncWindowConflictError``（40900，
  E010）；已完成/失败的窗口允许重跑——复用同一行并重置执行态，金额不变由
  uk_bill 覆盖写保证（F026），不靠拒绝重跑换幂等。
- ``build_bill_row``：汇率折算（缺失不阻断入库，database.md 表 9）+ 标签归属
  （复用 cost.services 纯函数，§5.3 两处共享同一份规则）。
- ``upsert_bill_lines``：按 uk_bill 批量 upsert（增量同步路径）。
- ``recalc_bill_window``：重算窗口 = 同事务 DELETE + INSERT 覆盖写（非增量累加）。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.billing.models import CloudBillDetail, SyncLog
from apps.cost.services import resolve_tag_ownership
from common.exceptions import SyncWindowConflictError
from common.readers import MissingDictEntryError, get_exchange_rate
from providers.base import BillLine

if TYPE_CHECKING:  # 仅类型标注，避免运行期循环导入
    from apps.billing.models import CloudAccount

logger = logging.getLogger(__name__)

_CNY = "CNY"
_RATE_ONE = Decimal(1)
_Q8 = Decimal("0.00000001")

# uk_bill 冲突判定列与覆盖列（增量 upsert 用）
_UK_BILL_FIELDS = ["cloud_account", "resource_type", "instance_id", "bill_date", "charge_type"]
_BILL_UPDATE_FIELDS = [
    "region",
    "project_tag",
    "raw_tags",
    "tag_status",
    "currency",
    "amount",
    "exchange_rate",
    "amount_cny",
    "bill_month",
    "update_time",
]

_BillKey = tuple[int, str, str | None, date, str]


def _bill_key(row: CloudBillDetail) -> _BillKey:
    return (
        row.cloud_account_id,
        row.resource_type,
        row.instance_id,
        row.bill_date,
        row.charge_type,
    )


# ---------- 同步窗口（uk_sync_window） ----------


def claim_sync_window(account: CloudAccount, sync_type: str, start: date, end: date) -> SyncLog:
    """占用同步窗口；运行中重复占用抛 40900（E010）。

    ``select_for_update`` 序列化并发争抢：先到者建行占窗口，后到者在运行态被拒。
    成功/失败态的窗口可重跑（复用同一行并重置计数与失败原因）。
    """
    with transaction.atomic():
        row = (
            SyncLog.objects.select_for_update()
            .filter(
                cloud_account=account,
                sync_type=sync_type,
                bill_date_start=start,
                bill_date_end=end,
            )
            .first()
        )
        if row is None:
            return SyncLog.objects.create(
                cloud_account=account,
                sync_type=sync_type,
                bill_date_start=start,
                bill_date_end=end,
                status=SyncLog.Status.RUNNING,
            )
        if row.status == SyncLog.Status.RUNNING:
            raise SyncWindowConflictError
        SyncLog.objects.filter(pk=row.pk).update(
            status=SyncLog.Status.RUNNING,
            insert_count=0,
            update_count=0,
            error_msg=None,
            start_time=timezone.now(),
            end_time=None,
        )
        row.refresh_from_db()
        return row


def release_sync_window(
    row: SyncLog,
    status: str,
    *,
    insert_count: int = 0,
    update_count: int = 0,
    error_msg: str | None = None,
) -> None:
    """同步收尾：写终态与计数（成功/失败），由同步任务在 finally 语义处调用。"""
    row.status = status
    row.insert_count = insert_count
    row.update_count = update_count
    row.error_msg = error_msg
    row.end_time = timezone.now()
    row.save(update_fields=["status", "insert_count", "update_count", "error_msg", "end_time"])


# ---------- 折算与标签归属（导入前置） ----------


def _resolve_exchange(line: BillLine) -> tuple[Decimal | None, Decimal | None]:
    """按 bill_date 查汇率折算；缺失汇率不阻断入库（exchange_rate/amount_cny 落 NULL，
    标记后由后台补录并回溯重算，database.md 表 9 / PRD 2.1.2）。"""
    if line.currency == _CNY:
        rate = _RATE_ONE
    else:
        try:
            rate = get_exchange_rate(line.currency, line.bill_date)
        except MissingDictEntryError:
            logger.warning(
                "汇率缺失，账单先入库待补录 currency=%s bill_date=%s",
                line.currency,
                line.bill_date,
            )
            return None, None
    amount_cny = (line.amount * rate).quantize(_Q8, rounding=ROUND_HALF_UP)
    return rate, amount_cny


def build_bill_row(
    account: CloudAccount, line: BillLine, *, tag_values: Sequence[str | None]
) -> CloudBillDetail:
    """BillLine → 待落库模型实例：标签归属（§5.3 共享规则）+ 汇率折算。

    ``tag_values`` 为同步任务从厂商原始标签中取出的项目标签值集合（键名可配置，
    PRD 2.1.1）；原始标签串原样落 ``raw_tags`` 供治理页追溯。
    """
    ownership = resolve_tag_ownership(tag_values)
    rate, amount_cny = _resolve_exchange(line)
    return CloudBillDetail(
        cloud_account=account,
        region=line.region,
        instance_id=line.instance_id,
        resource_type=line.resource_type,
        project_tag=ownership.project_tag,
        raw_tags=line.raw_tags,
        tag_status=ownership.tag_status,
        charge_type=line.charge_type,
        currency=line.currency,
        amount=line.amount,
        exchange_rate=rate,
        amount_cny=amount_cny,
        bill_date=line.bill_date,
        bill_month=f"{line.bill_date:%Y-%m}",
    )


# ---------- 账单幂等写（uk_bill） ----------


def upsert_bill_lines(rows: Iterable[CloudBillDetail]) -> tuple[int, int]:
    """按 uk_bill 批量 upsert，返回 (inserted, updated)。

    同批内重复键取后者（避免 ON CONFLICT 同行二次影响）；已存在键走覆盖更新
    （金额口径以最新一次同步为准，重复同步不翻倍，F026）。
    """
    deduped = {_bill_key(row): row for row in rows}
    objs = list(deduped.values())
    if not objs:
        return 0, 0
    existing = set(
        CloudBillDetail.objects.filter(
            cloud_account_id__in={row.cloud_account_id for row in objs},
            bill_date__in={row.bill_date for row in objs},
        ).values_list(
            "cloud_account_id",
            "resource_type",
            "instance_id",
            "bill_date",
            "charge_type",
        )
    )
    inserted = len(set(deduped) - existing)
    updated = len(set(deduped) & existing)
    CloudBillDetail.objects.bulk_create(
        objs,
        update_conflicts=True,
        update_fields=_BILL_UPDATE_FIELDS,
        unique_fields=_UK_BILL_FIELDS,
    )
    return inserted, updated


def recalc_bill_window(
    account: CloudAccount, start: date, end: date, rows: Iterable[CloudBillDetail]
) -> tuple[int, int]:
    """重算窗口：同事务 DELETE + INSERT 覆盖写（§6 uk_bill，非增量累加）。

    供月末重算/汇率回溯重算使用：窗口内旧行整体替换为新批次，窗口外不受影响。
    """
    with transaction.atomic():
        deleted, _ = CloudBillDetail.objects.filter(
            cloud_account=account, bill_date__range=(start, end)
        ).delete()
        deduped = {_bill_key(row): row for row in rows}
        if deduped:
            CloudBillDetail.objects.bulk_create(list(deduped.values()))
        return deleted, len(deduped)
