"""四判据的 SQL 表达与 `judge` 的集合等价性（spec §9 D14-e①）。

`idle_branches()` 是 `judge` 的下推表达：本轮把判定从 Python 搬进 SQL，代价是口径出现
两份表达。这个文件就是那笔代价的保险——它把「两份表达必须永远同解」变成机器约束。
任何一侧改动（新增判据、改阈值语义、改 `status` 取值、改回退层级）都必须先在这里红一次。

命中总数 156 = ①45（prepaid×stopped×5 类型×3 模式×3 档）＋ ②30（postpaid×stopped，
仅 days∈{14,15} 两档过阈值 ⇒ 5×3×2）＋ ③27（eip×unbound×3 计费×3 模式×3 档）
＋ ④54（domain×{expired,expiring}×3 计费×3 模式×3 档）。四支因 `status` 单值互斥 ⇒ 可加。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import pytest
from django.db.models import Q
from django.utils import timezone

from apps.assets.idle_rules import (
    IDLE_DOMAIN_EXPIRED,
    IDLE_EIP_UNBOUND,
    IDLE_POSTPAID_STOPPED,
    IDLE_PREPAID_STOPPED,
    IDLE_SINCE,
    IDLE_SINCE_ALIAS,
    IDLE_TYPES,
    IdleConfig,
    idle_branches,
    judge,
)
from apps.assets.models import CloudAsset

CHARGE_TYPES: tuple[str | None, ...] = ("prepaid", "postpaid", None)
RESOURCE_TYPES: tuple[str, ...] = ("ecs", "rds", "eip", "nat", "domain")
FALLBACK_MODES: tuple[str, ...] = ("changed", "first_seen", "create_time")  # D11 三级
THRESHOLD = 14
DAYS_AROUND_THRESHOLD: tuple[int, ...] = (13, 14, 15)  # N-1 / N / N+1
EXPECTED_HITS = 156
EXPECTED_BY_TYPE = {
    IDLE_PREPAID_STOPPED: 45,
    IDLE_POSTPAID_STOPPED: 30,
    IDLE_EIP_UNBOUND: 27,
    IDLE_DOMAIN_EXPIRED: 54,
}
PREFIX = "eq-"


# 回退模式 → 该模式要写成 `now - days` 的列（D11 三级；`create_time` 由 auto_now_add
# 落库，只能落库后改写）
FALLBACK_COLUMN = {
    "changed": "status_changed_at",
    "first_seen": "first_seen_at",
    "create_time": "create_time",
}


def _rowspace() -> list[dict[str, object]]:
    """9 状态 × 3 计费（含 NULL）× 5 类型 × 3 回退模式 × 3 阈值档 = 1215 份定义。

    `instance_id` 末尾编码 `-{mode}-{days}`，后面的批量改写靠 `instance_id__endswith`
    定位，**不靠 `bulk_create` 的返回顺序去 zip**——那个顺序不是可依赖的确定性。
    """
    rows: list[dict[str, object]] = []
    for n, choice in enumerate(CloudAsset.Status.choices, start=1):
        status = choice[0]
        for charge_type in CHARGE_TYPES:
            for resource_type in RESOURCE_TYPES:
                for mode in FALLBACK_MODES:
                    for days in DAYS_AROUND_THRESHOLD:
                        rows.append(
                            {
                                "resource_type": resource_type,
                                "instance_id": f"{PREFIX}{n:02d}{charge_type or 'null'}"
                                f"-{resource_type}-{mode}-{days}",
                                "status": status,
                                "charge_type": charge_type,
                                "expire_time": None,  # 由 _make_rows 统一填，要与 now 同基
                                "status_changed_at": None,
                                "first_seen_at": None,
                            }
                        )
    return rows


def _make_rows(now: datetime) -> None:
    """落库整个 rowspace，再按 (模式, 档位) 分 9 组把三级时间戳统一写成 `now - days`。"""
    CloudAsset.objects.bulk_create(
        [
            CloudAsset(
                **{
                    k: (now + timedelta(days=3) if k == "expire_time" else v)
                    for k, v in row.items()
                }
            )
            for row in _rowspace()
        ]
    )
    for mode, days in [(m, d) for m in FALLBACK_MODES for d in DAYS_AROUND_THRESHOLD]:
        CloudAsset.objects.filter(instance_id__endswith=f"{mode}-{days}").update(
            **{FALLBACK_COLUMN[mode]: now - timedelta(days=days)}
        )


def _branch_ids(cfg: IdleConfig, now: datetime, types: list[str]) -> set[int]:
    """仅用 `idle_branches()` 组装谓词（不经过生产读路径）取命中 id——Task 1 阶段的被测对象。"""
    predicate = Q(*[idle_branches(cfg, now)[t] for t in types], _connector="OR")
    return set(
        CloudAsset.objects.filter(released_at__isnull=True)
        .annotate(**{IDLE_SINCE_ALIAS: IDLE_SINCE})
        .filter(predicate)
        .values_list("id", flat=True)
    )


def _judge_map(cfg: IdleConfig, now: datetime) -> dict[int, str]:
    """`judge` 侧的 {pk: idle_type}——口径以它为准。"""
    out: dict[int, str] = {}
    for asset in CloudAsset.objects.filter(instance_id__startswith=PREFIX):
        verdict = judge(asset, cfg, now)
        if verdict is not None:
            out[asset.pk] = verdict.idle_type
    return out


@pytest.mark.django_db
def test_rowspace_self_proof() -> None:
    """先证明数据真的造出来了：1215 行、命中 156、四支构成 45/30/27/54。

    没有这一条，后面的等价断言可能在「两边都空」上假绿。
    """
    now = timezone.now()
    cfg = IdleConfig(idle_stopped_days=THRESHOLD)
    _make_rows(now)
    assert CloudAsset.objects.filter(instance_id__startswith=PREFIX).count() == 1215
    jm = _judge_map(cfg, now)
    assert len(jm) == EXPECTED_HITS
    by_type: dict[str, int] = defaultdict(int)
    for idle_type in jm.values():
        by_type[idle_type] += 1
    assert dict(by_type) == EXPECTED_BY_TYPE


@pytest.mark.django_db
@pytest.mark.parametrize("idle_type", list(IDLE_TYPES))
def test_each_sql_branch_equals_judge_for_that_type(idle_type: str) -> None:
    """逐支等价：SQL 支 `t` 的命中集合 == `judge` 判为 `t` 的集合（支间互斥 ⇒ 可直接比）。"""
    now = timezone.now()
    cfg = IdleConfig(idle_stopped_days=THRESHOLD)
    _make_rows(now)
    jm = _judge_map(cfg, now)
    assert _branch_ids(cfg, now, [idle_type]) == {pk for pk, t in jm.items() if t == idle_type}


@pytest.mark.django_db
def test_all_branches_or_equals_full_judge_set() -> None:
    """全集等价：四支 OR 的命中集合 == `judge` 全部命中集合（`idleType` 不筛的那一档）。"""
    now = timezone.now()
    cfg = IdleConfig(idle_stopped_days=THRESHOLD)
    _make_rows(now)
    assert _branch_ids(cfg, now, list(IDLE_TYPES)) == set(_judge_map(cfg, now))
