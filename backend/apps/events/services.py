"""事件与厂商消息幂等入库（engineering-conventions §6：uk_event_dedup / uk_vendor_msg）。

去重语义（F050 / F056）：

- 厂商消息按 ``(provider, message_id)`` 不重复入库，重复回调幂等返回既有行；
- 事件按 ``dedup_key`` 去重——同一告警未恢复前重复检测/重复消息不产生第二条
  事件；恢复后再次发生由调用方生成新 ``dedup_key``（含时间戳，F050）。

``get_or_create`` 依赖数据库唯一键兜底并发（§6：唯一键优先于代码判断），
命中已存在键时 ``created=False``，调用方据此把消息流水标记为 duplicated。
"""

from __future__ import annotations

import calendar
import logging
from datetime import date
from typing import Any

from django.db.models import Sum
from django.utils import timezone

from apps.assets.models import CloudAsset
from apps.cost.models import ProjectBudget, ProjectCostDaily
from apps.cost.services import budget_ratio_pct
from apps.events.models import CloudEvent, VendorMessageLog
from common.readers import get_platform_setting, require_event_type

logger = logging.getLogger(__name__)


def upsert_event(**fields: Any) -> tuple[CloudEvent, bool]:
    """按 dedup_key 去重落事件，返回 (event, created)。

    除 ``dedup_key`` 外的字段全部经 ``fields`` 传入（新事件时作为初始值，
    已存在事件不回写——状态流转走事件处理接口，不靠重复消息覆盖）。
    """
    dedup_key = fields.pop("dedup_key")
    event, created = CloudEvent.objects.get_or_create(dedup_key=dedup_key, defaults=fields)
    return event, created


def record_vendor_message(**fields: Any) -> tuple[VendorMessageLog, bool]:
    """按 (provider, message_id) 去重落厂商消息流水，返回 (log, created)。

    全量流水含重复消息的去重语义：重复接收不二次入库（uk_vendor_msg 拦截），
    幂等返回既有行与 ``created=False``，调用方据此置 ``mapped_status=duplicated``。
    """
    provider = fields.pop("provider")
    message_id = fields.pop("message_id")
    log, created = VendorMessageLog.objects.get_or_create(
        provider=provider, message_id=message_id, defaults=fields
    )
    return log, created


# ---------- 平台自算检测（tasks.md 任务 8 / PRD 3.12-8） ----------
#
# 两类厂商消息不覆盖的自算事件，均 source=rule、按业务键 dedup 去重，重复扫描幂等：
# 域名到期（cloud_asset.expire_time，T-30/T-7/T-1 各一次，过期转高危）与预算超支。
# 级别取 event_type_dict.default_level（唯一来源，不硬编码）。


def _emit_domain_event(asset: CloudAsset, code: str, days: int, tier: int | None) -> int:
    """落一条域名到期/过期事件，返回是否新建（1/0）。

    dedup_key：过期 ``expired:{域名}``；即将到期 ``expiring:{域名}:{档位}``——
    每档只产生一次（PRD 3.12-8.1 去重），跨档位互不覆盖。
    """
    level = require_event_type(code).default_level
    domain = asset.instance_id
    if code == "expired":
        dedup_key = f"expired:{domain}"
        title = f"域名 {domain} 已过期 {-days} 天"
    else:
        dedup_key = f"expiring:{domain}:{tier}"
        title = f"域名 {domain} 将在 {days} 天后到期"
    _, created = upsert_event(
        dedup_key=dedup_key,
        event_type=code,
        event_level=level,
        source=CloudEvent.Source.RULE,
        resource_type="domain",
        resource_id=domain,
        instance_name=asset.instance_name,
        cloud_account=asset.cloud_account,
        provider=asset.registrar,
        region=asset.region,
        project_tag=asset.project_tag,
        title=title,
        metric_json={
            "expireTime": asset.expire_time.isoformat() if asset.expire_time else None,
            "daysUntil": days,
            "noticeDays": tier,
        },
        occurred_at=timezone.now(),
    )
    return 1 if created else 0


def detect_domain_expiry(today: date | None = None) -> int:
    """扫描域名资产，按到期档位产生 expiring/expired 事件，返回新建事件数。

    口径（PRD 3.13-4 / 3.12-8）：
    - 仅 ``resource_type=domain`` 且 ``expire_time`` 非空、未释放（``released_at`` 为空）的资产；
    - 档位取 ``platform_setting.expire_notice_days``（默认 [30,7,1]）；
    - ``days_until = expire_time.date() - today``：``<0`` → expired（严重，过期后不再产 expiring）；
      ``0 ≤ days_until ≤ 档位`` → 每个命中档位各产一次 expiring（警告）。
    - 累积语义：扫描首次见到资产即补齐所有已命中档位，避免漏扫丢档；dedup 保证不重复。
    """
    today = today or timezone.localdate()
    tiers = get_platform_setting("expire_notice_days")
    domains = CloudAsset.objects.filter(
        resource_type="domain",
        released_at__isnull=True,
        expire_time__isnull=False,
    )
    created = 0
    for asset in domains:
        if asset.expire_time is None:  # 供 mypy 收窄；查询已过滤非空
            continue
        days = (asset.expire_time.date() - today).days
        if days < 0:
            created += _emit_domain_event(asset, "expired", days, None)
            continue
        for tier in tiers:
            if days <= tier:
                created += _emit_domain_event(asset, "expiring", days, tier)
    return created


def detect_budget_overrun(bill_month: str | None = None, today: date | None = None) -> int:
    """扫描某账期月的项目预算，首次超 100% 产生 budget_overrun 事件，返回新建数。

    口径（PRD 2.2.2 / 3.12-8）：
    - ``bill_month`` 缺省取 ``today`` 的 ``YYYY-MM``；只扫该月、且 ``budget_amount>0`` 的预算；
    - 项目支出 = 该月 ``project_cost_daily`` 中 **仅 NORMAL 行** 的 ``amount`` 之和
      （未分配/冲突行恒无预算、不计入，PRD 2.2.2）；
    - 占比 = ``budget_ratio_pct(current, budget)``，``>100`` 才算超支（恰好 100% 不算）；
    - dedup_key ``budget_overrun:{项目标签}:{账期月}`` → 某项目某账期只产生一次，重复扫描幂等。
    """
    today = today or timezone.localdate()
    month = bill_month or f"{today.year:04d}-{today.month:02d}"
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    end = date(year, mon, calendar.monthrange(year, mon)[1])
    normal = ProjectCostDaily.TagStatus.NORMAL
    level = require_event_type("budget_overrun").default_level

    created = 0
    budgets = ProjectBudget.objects.filter(bill_month=month, budget_amount__gt=0)
    for budget in budgets:
        current = ProjectCostDaily.objects.filter(
            project_tag=budget.project_tag,
            tag_status=normal,
            stat_date__gte=start,
            stat_date__lte=end,
        ).aggregate(total=Sum("amount"))["total"]
        ratio = budget_ratio_pct(current, budget.budget_amount)
        if ratio is None or ratio <= 100:
            continue
        _, was_created = upsert_event(
            dedup_key=f"budget_overrun:{budget.project_tag}:{month}",
            event_type="budget_overrun",
            event_level=level,
            source=CloudEvent.Source.RULE,
            project_tag=budget.project_tag,
            title=f"项目 {budget.project_tag} {month} 预算超支",
            metric_json={
                "billMonth": month,
                "projectTag": budget.project_tag,
                "amount": str(current),
                "budget": str(budget.budget_amount),
                "ratio": str(ratio),
            },
            occurred_at=timezone.now(),
        )
        created += 1 if was_created else 0
    return created
