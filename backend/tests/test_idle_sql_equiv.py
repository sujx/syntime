"""四判据的 SQL 表达与 `judge` 的集合等价性（spec §9 D14-e①）。

`idle_branches()` 是 `judge` 的下推表达：本轮把判定从 Python 搬进 SQL，代价是口径出现
两份表达。这个文件就是那笔代价的保险——它把「两份表达必须永远同解」变成机器约束。
任何一侧改动（新增判据、改阈值语义、改 `status` 取值、改回退层级）都必须先在这里红一次。

保险丝有两格，别把第一格当成第二格：
- rowspace（`PREFIX`，1215 行全笛卡尔）钉四支谓词、`status` 取值、阈值边界 13/14/15，
  以及三级回退**各自单独非空**的那种行。
- 两条单行用例（`PREC_PREFIX` / `THRESH_PREFIX`）钉 rowspace 造不出的那两格：第 1、2 级
  同时非空时取哪一级（生产 `align_assets` / `upsert_domain` 就是这种行 ⇒ 层级互换必须红），
  以及判据 ② 的阈值确实取自 `config`（写成常数 14 必须红）。两侧取数都按各自前缀圈定，
  用例末尾把该前缀的行删干净——三个前缀互不包含，任何一侧都不会读到别人的行。

本文件不覆盖的两格（登记在此，免得把上面那句读过头）：三档时间戳全空——`create_time` 由
`auto_now_add` 恒非空，DB 里造不出这种行，Python 侧那一格由 `test_idle_rules.py` 的
`test_stopped_since_three_level_fallback` 守着；判据 ④ 的「已过期」与「台账无到期时间」
两档文案——rowspace 的 `expire_time` 恒为 `now + 3d`，只走到「N 天后到期」那一档，但支 ④
谓词根本不带 `expire_time` 条件（D14-c），文案分支只在 `judge` 出参里分家、不动命中集合。

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
# 两条单行用例的独立前缀：与 rowspace 的前缀不重叠 ⇒ 1215 / 156 / 45·30·27·54 读数不受影响
PREC_PREFIX = "prec-"
THRESH_PREFIX = "thresh-"


# 回退模式 → 该模式要写成 `now - days` 的列（D11 三级；`create_time` 由 auto_now_add
# 落库，只能落库后改写）
FALLBACK_COLUMN = {
    "changed": "status_changed_at",
    "first_seen": "first_seen_at",
    "create_time": "create_time",
}


def _rowspace() -> list[dict[str, object]]:
    """9 状态 × 3 计费（含 NULL）× 5 类型 × 3 回退模式 × 3 阈值档 = 1215 份定义。

    `instance_id` 末尾编码 `-{mode}-{days}`，后面的批量改写靠 `PREFIX` ＋ `instance_id__endswith`
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
    """落库整个 rowspace，再按 (模式, 档位) 分 9 组把三级时间戳统一写成 `now - days`。

    `expire_time` 统一填 `now + 3d`：判据 ④ 因此只走到「N 天后到期」那一档文案，
    「已过期」与「台账无到期时间」两档不在本数据里（它们由 `test_idle_rules.py` 纯函数侧
    钉住）。下推侧不亏：支 ④ 的谓词只有 `resource_type` ＋ `status`，**一个
    `expire_time` 条件都不带**（D14-c ⇒ SQL 里不做日期差），三档文案在 `judge` 里怎么分家
    都不改变命中集合 ⇒ rowspace 造哪一档都一样等价。

    批量改写带上 `instance_id__startswith=PREFIX`：这条 `update` 走的是全表谓词，不圈前缀
    就会碰到与本文件无关的行。
    """
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
        CloudAsset.objects.filter(
            instance_id__startswith=PREFIX, instance_id__endswith=f"-{mode}-{days}"
        ).update(**{FALLBACK_COLUMN[mode]: now - timedelta(days=days)})


def _branch_ids(cfg: IdleConfig, now: datetime, types: list[str], prefix: str = PREFIX) -> set[int]:
    """仅用 `idle_branches()` 组装谓词（不经过生产读路径）取命中 id——Task 1 阶段的被测对象。

    `prefix` 与 `judge` 侧 `_judge_map` 用同一个：SQL 侧只带 `released_at__isnull=True` 就会
    把库里其它前缀的行也算进来，两侧取数范围必须一致，否则比的是两个不同的集合。
    """
    predicate = Q(*[idle_branches(cfg, now)[t] for t in types], _connector="OR")
    return set(
        CloudAsset.objects.filter(released_at__isnull=True, instance_id__startswith=prefix)
        .annotate(**{IDLE_SINCE_ALIAS: IDLE_SINCE})
        .filter(predicate)
        .values_list("id", flat=True)
    )


def _judge_map(cfg: IdleConfig, now: datetime, prefix: str = PREFIX) -> dict[int, str]:
    """`judge` 侧的 {pk: idle_type}——口径以它为准。"""
    out: dict[int, str] = {}
    for asset in CloudAsset.objects.filter(instance_id__startswith=prefix):
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


def _make_stopped_rows(
    now: datetime, specs: list[tuple[str, int | None, int | None]]
) -> dict[str, int]:
    """按 `(instance_id, 第 1 级天数, 第 2 级天数)` 落库几行按量停机资产，返回 {instance_id: pk}。

    rowspace 每行只把「自己那一档」的列写成 `now - days`、另两列留 NULL（`models.py` 里两列
    都没有 default）⇒ 第 1、2 级同时非空那种行在这里造不出来，只能单行造。而生产真会写成
    这样：`align_assets` 与 `upsert_domain` 两条路径都同时落 `status_changed_at` 和
    `first_seen_at`，所以判据 ② 的日期来源是**有层级**的，互换 Coalesce 前两级就得红。
    """
    CloudAsset.objects.bulk_create(
        [
            CloudAsset(
                resource_type="ecs",
                instance_id=instance_id,
                status=CloudAsset.Status.STOPPED,
                charge_type="postpaid",
                status_changed_at=None
                if changed_days is None
                else now - timedelta(days=changed_days),
                first_seen_at=None
                if first_seen_days is None
                else now - timedelta(days=first_seen_days),
            )
            for instance_id, changed_days, first_seen_days in specs
        ]
    )
    return {
        instance_id: int(CloudAsset.objects.get(instance_id=instance_id).pk)
        for instance_id, _, _ in specs
    }


@pytest.mark.django_db
def test_idle_since_takes_level1_before_level2() -> None:
    """D11 层级：`IDLE_SINCE` 前两级互换必须红——两行只差「旧日期落在哪一列」。

    期望值各自写明（阈值 14）：
    - `prec-old-l1`：`status_changed_at = now - 20d`、`first_seen_at = now - 1d` ⇒ 取第 1 级
      的 20 天 ⇒ 20 ≥ 14 ⇒ **命中**。
    - `prec-old-l2`（镜像）：第 1 级只有 1 天 ⇒ 1 < 14 ⇒ **不命中**，哪怕第 2 级已 20 天。
    互换 Coalesce 前两级后两行同时翻面（前者掉出、后者挤进），而 `judge` 的 `or` 链不动
    ⇒ 两侧集合立刻对不上，第一条断言就红。
    """
    now = timezone.now()
    cfg = IdleConfig(idle_stopped_days=THRESHOLD)
    old_l1 = f"{PREC_PREFIX}old-l1"
    old_l2 = f"{PREC_PREFIX}old-l2"
    pks = _make_stopped_rows(now, [(old_l1, 20, 1), (old_l2, 1, 20)])

    ids = _branch_ids(cfg, now, [IDLE_POSTPAID_STOPPED], PREC_PREFIX)
    assert ids == {pks[old_l1]}  # 第 1 级旧 ⇒ 命中
    assert pks[old_l2] not in ids  # 第 1 级新 ⇒ 第 2 级的 20 天不作数

    jm = _judge_map(cfg, now, PREC_PREFIX)
    assert jm == {pks[old_l1]: IDLE_POSTPAID_STOPPED}  # judge 同解：同样只认第 1 级
    assert _branch_ids(cfg, now, list(IDLE_TYPES), PREC_PREFIX) == set(jm)

    CloudAsset.objects.filter(instance_id__startswith=PREC_PREFIX).delete()


@pytest.mark.django_db
def test_stopped_threshold_comes_from_config() -> None:
    """阈值来源：把 `timedelta(days=config.idle_stopped_days)` 写死成常数必须红。

    rowspace 里 `IdleConfig(idle_stopped_days=THRESHOLD)` 恒等于 14，写死常数不会被它抓到，
    所以这里换阈值 7、换前缀单造三行（档位 6 / 7 / 13，13 特意落在 7 与 14 之间）：
    写死 14 ⇒ 7 天与 13 天两行在 SQL 侧掉出、`judge` 仍判命中 ⇒ 红。
    """
    now = timezone.now()
    cfg = IdleConfig(idle_stopped_days=7)
    below = f"{THRESH_PREFIX}d6"
    exact = f"{THRESH_PREFIX}d7"
    above = f"{THRESH_PREFIX}d13"
    pks = _make_stopped_rows(now, [(below, 6, None), (exact, 7, None), (above, 13, None)])

    ids = _branch_ids(cfg, now, [IDLE_POSTPAID_STOPPED], THRESH_PREFIX)
    assert ids == {pks[exact], pks[above]}  # ≥ 7 命中；恰好 7 天也算
    assert pks[below] not in ids  # 6 天 < 7 ⇒ 不命中

    jm = _judge_map(cfg, now, THRESH_PREFIX)
    assert jm == {pks[exact]: IDLE_POSTPAID_STOPPED, pks[above]: IDLE_POSTPAID_STOPPED}
    assert ids == set(jm)

    # 同一批行只把阈值改成 14：两侧一起翻面（13 天那行也掉出）⇒ 证明动的是 config 不是数据
    cfg14 = IdleConfig(idle_stopped_days=THRESHOLD)
    assert _branch_ids(cfg14, now, [IDLE_POSTPAID_STOPPED], THRESH_PREFIX) == set()
    assert _judge_map(cfg14, now, THRESH_PREFIX) == {}

    # 收尾把这一格自己的行删干净——前缀纪律见模块 docstring
    CloudAsset.objects.filter(instance_id__startswith=THRESH_PREFIX).delete()
