"""§6 资产全量对齐单测（uk_asset / F045）：upsert 幂等、缺席软删、复活、时间戳语义。"""

from datetime import UTC, datetime, timedelta

import pytest

import apps.assets.services as services
from apps.assets.models import CloudAsset
from apps.assets.services import align_assets
from apps.billing.models import CloudAccount


@pytest.fixture
def account() -> CloudAccount:
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc1",
        account_type="main",
        ak_cipher="x",
        sk_cipher="y",
    )


def _asset(account: CloudAccount | None, instance_id: str, status: str = "running") -> CloudAsset:
    return CloudAsset(
        cloud_account=account,
        resource_type="ecs",
        instance_id=instance_id,
        status=status,
        region="cn-hangzhou",
    )


# ---------- 首次发现与重复对齐 ----------


@pytest.mark.django_db
def test_align_new_assets_set_seen_timestamps(account):
    result = align_assets(account, [_asset(account, "i-1")])
    assert result.upserted == 1
    assert result.released == 0
    row = CloudAsset.objects.get()
    assert row.first_seen_at == row.last_seen_at
    assert row.status_changed_at is not None
    assert row.released_at is None


@pytest.mark.django_db
def test_align_repeat_keeps_first_seen(account):
    align_assets(account, [_asset(account, "i-1")])
    first_seen = CloudAsset.objects.get().first_seen_at
    assert first_seen is not None
    align_assets(account, [_asset(account, "i-1")])
    row = CloudAsset.objects.get()
    assert CloudAsset.objects.count() == 1  # 不产生重复资产（uk_asset）
    assert row.first_seen_at == first_seen
    assert row.last_seen_at is not None
    assert row.last_seen_at >= first_seen


@pytest.mark.django_db
def test_align_status_change_refreshes_status_changed_at(account, monkeypatch):
    """status 变化刷新 status_changed_at、不变则保持（V1.14 闲置判定口径）。

    用确定性时钟替换 ``services.timezone``：align_assets 每次调用只取一次 now()，
    故三次对齐拿到严格递增的时间戳，消除「两次对齐落在同一微秒致 ``>`` 断言偶发
    失败」的时钟分辨率竞争（auto_now 走真实 django.utils.timezone，不受影响）。
    """
    base = datetime(2026, 9, 21, tzinfo=UTC)
    ticks = iter(base + timedelta(seconds=i) for i in range(3))

    class _Clock:
        @staticmethod
        def now() -> datetime:
            return next(ticks)

    monkeypatch.setattr(services, "timezone", _Clock)

    align_assets(account, [_asset(account, "i-1", status="running")])
    first_change = CloudAsset.objects.get().status_changed_at
    assert first_change == base

    align_assets(account, [_asset(account, "i-1", status="stopped")])
    second_change = CloudAsset.objects.get().status_changed_at
    assert second_change == base + timedelta(seconds=1)
    assert second_change > first_change

    # 状态不变时不刷新
    align_assets(account, [_asset(account, "i-1", status="stopped")])
    assert CloudAsset.objects.get().status_changed_at == second_change


# ---------- 缺席软删与复活（F045） ----------


@pytest.mark.django_db
def test_align_missing_asset_marked_released(account):
    align_assets(account, [_asset(account, "i-1"), _asset(account, "i-2")])
    result = align_assets(account, [_asset(account, "i-1")])  # i-2 缺席
    assert result.released == 1
    released = CloudAsset.objects.get(instance_id="i-2")
    assert released.released_at is not None  # 软删，非物理删除
    assert CloudAsset.objects.count() == 2
    assert CloudAsset.objects.get(instance_id="i-1").released_at is None


@pytest.mark.django_db
def test_align_released_not_retimestamped(account):
    align_assets(account, [_asset(account, "i-1")])
    align_assets(account, [])
    released_at = CloudAsset.objects.get().released_at
    align_assets(account, [])
    assert CloudAsset.objects.get().released_at == released_at


@pytest.mark.django_db
def test_align_reappearing_asset_revived(account):
    align_assets(account, [_asset(account, "i-1")])
    first_seen = CloudAsset.objects.get().first_seen_at
    align_assets(account, [])  # 释放
    assert CloudAsset.objects.get().released_at is not None
    align_assets(account, [_asset(account, "i-1")])  # 重新出现
    row = CloudAsset.objects.get()
    assert row.released_at is None  # 复活
    assert row.first_seen_at == first_seen  # 首次发现不变
    assert CloudAsset.objects.count() == 1


# ---------- 无归属账号资产（域名等，cloud_account 为空） ----------


@pytest.mark.django_db
def test_align_domain_assets_with_null_account():
    def _domain() -> CloudAsset:
        return CloudAsset(
            cloud_account=None,
            resource_type="domain",
            instance_id="example.com",
            status="normal",
        )

    result = align_assets(None, [_domain()])
    assert result.upserted == 1
    align_assets(None, [_domain()])
    assert CloudAsset.objects.count() == 1  # NULL 归属键对齐同样幂等（NULLS NOT DISTINCT）


@pytest.mark.django_db
def test_align_only_touches_its_own_account(account):
    other = CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc2",
        account_type="main",
        ak_cipher="x",
        sk_cipher="y",
    )
    align_assets(other, [_asset(other, "i-1")])
    result = align_assets(account, [])  # account 名下无资产
    assert result.released == 0  # 不误伤 other 账号的资产
    assert CloudAsset.objects.get(instance_id="i-1").released_at is None
