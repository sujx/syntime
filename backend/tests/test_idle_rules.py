"""接缝 A 单测（spec §5 → 覆盖 F063）：四类命中、阈值翻转、三级回退、eip 停机归 ①。

不打 DB——`judge` 是纯函数，喂未保存的 `CloudAsset` 实例就能钉死全部口径。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apps.assets.idle_rules import (
    IDLE_DOMAIN_EXPIRED,
    IDLE_EIP_UNBOUND,
    IDLE_POSTPAID_STOPPED,
    IDLE_PREPAID_STOPPED,
    IdleConfig,
    judge,
)
from apps.assets.models import CloudAsset

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CONFIG = IdleConfig(idle_stopped_days=14)
STOPPED = CloudAsset.Status.STOPPED


def _asset(**overrides: object) -> CloudAsset:
    base: dict[str, object] = {
        "resource_type": "ecs",
        "instance_id": "i-1",
        "status": CloudAsset.Status.RUNNING,
        "charge_type": "postpaid",
    }
    base.update(overrides)
    return CloudAsset(**base)  # type: ignore[arg-type]


# ---------- 判据 ① 包年包月已停机 ----------


def test_prepaid_stopped_hits() -> None:
    verdict = judge(_asset(charge_type="prepaid", status=STOPPED), CONFIG, NOW)
    assert verdict is not None
    assert verdict.idle_type == IDLE_PREPAID_STOPPED
    assert verdict.reason == "包年包月资源已停机"
    assert verdict.key_metric == {}


# ---------- 判据 ② 按量长期停机 ----------


def test_postpaid_stopped_over_threshold_hits() -> None:
    verdict = judge(_asset(status=STOPPED, status_changed_at=NOW - timedelta(days=15)), CONFIG, NOW)
    assert verdict is not None
    assert verdict.idle_type == IDLE_POSTPAID_STOPPED
    assert verdict.key_metric == {"stoppedDays": 15, "thresholdDays": 14}
    assert verdict.reason == "按量付费已停机 15 天（阈值 14 天）"


def test_postpaid_stopped_below_threshold_absent() -> None:
    """F063「按量停机不足 N 天不出现」。"""
    asset = _asset(status=STOPPED, status_changed_at=NOW - timedelta(days=13))
    assert judge(asset, CONFIG, NOW) is None


def test_threshold_change_flips_result() -> None:
    """F063「调整 N 后结果即时变化」的口径层证明：同一行，N 变则结论变。"""
    asset = _asset(status=STOPPED, status_changed_at=NOW - timedelta(days=15))
    assert judge(asset, IdleConfig(idle_stopped_days=30), NOW) is None
    assert judge(asset, IdleConfig(idle_stopped_days=7), NOW) is not None


def test_stopped_since_three_level_fallback() -> None:
    """spec §8-D11：status_changed_at → first_seen_at → create_time。"""
    by_first_seen = judge(
        _asset(status=STOPPED, first_seen_at=NOW - timedelta(days=20)), CONFIG, NOW
    )
    assert by_first_seen is not None and by_first_seen.key_metric["stoppedDays"] == 20

    by_create_time = judge(
        _asset(status=STOPPED, create_time=NOW - timedelta(days=30)), CONFIG, NOW
    )
    assert by_create_time is not None and by_create_time.key_metric["stoppedDays"] == 30

    assert judge(_asset(status=STOPPED), CONFIG, NOW) is None  # 三个时间戳全空：无依据，不判


# ---------- 判据 ③ EIP 未绑定 ----------


def test_eip_unbound_hits() -> None:
    verdict = judge(_asset(resource_type="eip", status=CloudAsset.Status.UNBOUND), CONFIG, NOW)
    assert verdict is not None
    assert verdict.idle_type == IDLE_EIP_UNBOUND
    assert verdict.key_metric == {}


# ---------- 判据 ④ 域名已过期 / 即将到期 ----------


def test_domain_expired_and_expiring_hit_with_days() -> None:
    expired = judge(
        _asset(
            resource_type="domain",
            instance_id="a.test",
            status=CloudAsset.Status.EXPIRED,
            expire_time=NOW - timedelta(days=5),
        ),
        CONFIG,
        NOW,
    )
    assert expired is not None and expired.idle_type == IDLE_DOMAIN_EXPIRED
    assert expired.key_metric == {"daysUntilExpiry": -5}
    assert expired.reason == "域名已过期 5 天"

    expiring = judge(
        _asset(
            resource_type="domain",
            instance_id="b.test",
            status=CloudAsset.Status.EXPIRING,
            expire_time=NOW + timedelta(days=7),
        ),
        CONFIG,
        NOW,
    )
    assert expiring is not None and expiring.reason == "域名 7 天后到期"


def test_domain_without_expire_time_still_hits() -> None:
    """判据读的是存量 status，台账缺到期时间也不静默丢行（只是给不出天数）。"""
    verdict = judge(
        _asset(resource_type="domain", instance_id="c.test", status=CloudAsset.Status.EXPIRING),
        CONFIG,
        NOW,
    )
    assert verdict is not None and verdict.key_metric == {}


# ---------- 取序与不命中 ----------


def test_eip_stopped_prepaid_takes_criterion_one() -> None:
    """eip 但已停机 → 归 ①，命中 ③ 必须 `status=unbound`（resource_type 单独不够）。

    spec US-3 的「多命中按编号取第一类」在当前四判据下**结构上不可达**：①② 要 stopped、
    ③ 要 unbound、④ 要 expired/expiring，`status` 单值不可能同时成立；①与② 再由
    `charge_type` 互斥。`judge` 仍按 `IDLE_TYPES` 顺序短路，把该规则实现出来防止将来
    新增判据时口径漂移。
    """
    verdict = judge(_asset(resource_type="eip", charge_type="prepaid", status=STOPPED), CONFIG, NOW)
    assert verdict is not None
    assert verdict.idle_type == IDLE_PREPAID_STOPPED


def test_running_asset_and_released_asset_absent() -> None:
    assert judge(_asset(), CONFIG, NOW) is None
    released = _asset(charge_type="prepaid", status=STOPPED, released_at=NOW)
    assert judge(released, CONFIG, NOW) is None
