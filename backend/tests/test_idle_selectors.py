"""闲置清单读路径（api.md 接口16）：候选预筛等价性、判定、过滤、排序、每请求读配置。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assets.idle_rules import (
    IDLE_CANDIDATE_STATUSES,
    IDLE_DOMAIN_EXPIRED,
    IDLE_EIP_UNBOUND,
    IDLE_POSTPAID_STOPPED,
    IDLE_PREPAID_STOPPED,
    IdleConfig,
    IdleVerdict,
    judge,
)
from apps.assets.models import CloudAsset
from apps.assets.selectors import IdleQueryFilters, IdleRow, _sort_rows, list_idle_assets
from apps.billing.models import CloudAccount
from apps.core.models import PlatformSetting


@pytest.fixture
def account(db) -> CloudAccount:  # noqa: ANN001
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc1",
        account_type="main",
        ak_cipher="x",
        sk_cipher="y",
    )


def _types(rows) -> set[str]:  # noqa: ANN001
    return {r.verdict.idle_type for r in rows}


def _make(account: CloudAccount | None, **overrides: object) -> CloudAsset:
    base: dict[str, object] = {
        "cloud_account": account,
        "resource_type": "ecs",
        "instance_id": f"i-{CloudAsset.objects.count() + 1}",
        "status": CloudAsset.Status.RUNNING,
        "charge_type": "postpaid",
    }
    base.update(overrides)
    return CloudAsset.objects.create(**base)


@pytest.mark.django_db
def test_four_criteria_each_present(account: CloudAccount) -> None:
    now = timezone.now()
    _make(account, charge_type="prepaid", status=CloudAsset.Status.STOPPED)
    _make(account, status=CloudAsset.Status.STOPPED, status_changed_at=now - timedelta(days=15))
    _make(account, resource_type="eip", status=CloudAsset.Status.UNBOUND)
    _make(
        None,
        resource_type="domain",
        instance_id="a.test",
        status=CloudAsset.Status.EXPIRING,
        expire_time=now + timedelta(days=7),
        registrar="示例注册商",
    )
    _make(account, status=CloudAsset.Status.STOPPED, status_changed_at=now - timedelta(days=3))
    _make(account, instance_id="i-running")

    rows = list_idle_assets(IdleQueryFilters())
    assert len(rows) == 4  # 四判据各一行：多一行即泄漏（如 3 天阈值边界行混进 ②）
    assert _types(rows) == {
        IDLE_PREPAID_STOPPED,
        IDLE_POSTPAID_STOPPED,
        IDLE_EIP_UNBOUND,
        IDLE_DOMAIN_EXPIRED,
    }
    assert all(r.asset.instance_id != "i-running" for r in rows)


@pytest.mark.django_db
def test_released_asset_absent(account: CloudAccount) -> None:
    _make(
        account,
        charge_type="prepaid",
        status=CloudAsset.Status.STOPPED,
        released_at=timezone.now(),
    )
    assert list_idle_assets(IdleQueryFilters()) == []


@pytest.mark.django_db
def test_candidate_prefilter_is_lossless() -> None:
    """必要条件预筛不得改变结果：预筛集合之外的状态永远判不出闲置。

    逐个状态跑一遍 `CloudAsset.Status`，凡是候选集合外的都必须返回 None——
    这是 §8-D12 那条「SQL 只下推必要条件」的等价性证明。

    `probes` 是这条证明的**自证**：候选集合若扩到覆盖全部状态，循环体一次都不执行，
    断言会空转变绿。故把实际探测的组合数钉死为 50 = (9 状态 - 4 候选) × 2 计费 × 5 类型；
    状态枚举或候选集合任一侧变动，都必须同时改这个数字，否则本测试立刻失败。
    """
    now = timezone.now()
    probes = 0
    for status, *_ in CloudAsset.Status.choices:
        if status in {s.value if hasattr(s, "value") else s for s in IDLE_CANDIDATE_STATUSES}:
            continue
        for charge_type in ("prepaid", "postpaid"):
            for resource_type in ("ecs", "rds", "eip", "nat", "domain"):
                asset = CloudAsset(
                    resource_type=resource_type,
                    instance_id="probe",
                    status=status,
                    charge_type=charge_type,
                    expire_time=now,
                    status_changed_at=now - timedelta(days=99),
                )
                probes += 1
                assert judge(asset, IdleConfig(idle_stopped_days=1), now) is None, (
                    status,
                    charge_type,
                    resource_type,
                )
    assert probes == 50


@pytest.mark.django_db
def test_idle_type_filter_follows_single_verdict(account: CloudAccount) -> None:
    """`idleType` 过滤以 `judge` 的**唯一结论**为准：eip+prepaid+stopped 归 ①，筛 ③ 不出现。"""
    _make(
        account,
        resource_type="eip",
        instance_id="eip-1",
        charge_type="prepaid",
        status=CloudAsset.Status.STOPPED,
    )
    assert _types(list_idle_assets(IdleQueryFilters(idle_types=[IDLE_PREPAID_STOPPED]))) == {
        IDLE_PREPAID_STOPPED
    }
    assert list_idle_assets(IdleQueryFilters(idle_types=[IDLE_EIP_UNBOUND])) == []


@pytest.mark.django_db
def test_column_filters_and_keyword(account: CloudAccount) -> None:
    now = timezone.now()
    eip = _make(
        account,
        resource_type="eip",
        instance_id="eip-hz",
        status=CloudAsset.Status.UNBOUND,
        region="cn-hangzhou",
        project_tag="项目A",
    )
    domain = _make(
        None,
        resource_type="domain",
        instance_id="kw.test",
        instance_name="kw.test",
        status=CloudAsset.Status.EXPIRED,
        expire_time=now - timedelta(days=1),
        registrar="某注册商",
        region=None,
        project_tag=None,
    )
    # 名称与 ID 不同的行：让 keyword 的三列命中各自可归因（少一列 Q 就有一条断言红）
    named = _make(
        None,
        resource_type="domain",
        instance_id="only-id.test",
        instance_name="仅名称可搜",
        status=CloudAsset.Status.EXPIRED,
        expire_time=now - timedelta(days=1),
        registrar="另一家注册商",
        region=None,
        project_tag=None,
    )
    assert [r.asset.pk for r in list_idle_assets(IdleQueryFilters(region="cn-hangzhou"))] == [
        eip.pk
    ]
    assert [r.asset.pk for r in list_idle_assets(IdleQueryFilters(project_tag="项目A"))] == [eip.pk]
    assert [
        r.asset.pk for r in list_idle_assets(IdleQueryFilters(cloud_account_id=account.pk))
    ] == [eip.pk]
    assert list_idle_assets(IdleQueryFilters(resource_type="nat")) == []
    # keyword 命中 instance_id / instance_name / 域名注册商三列，逐个唯一归因
    assert [r.asset.pk for r in list_idle_assets(IdleQueryFilters(keyword="eip-"))] == [eip.pk]
    assert [r.asset.pk for r in list_idle_assets(IdleQueryFilters(keyword="仅名称可搜"))] == [
        named.pk
    ]
    assert [r.asset.pk for r in list_idle_assets(IdleQueryFilters(keyword="某注册商"))] == [
        domain.pk
    ]
    # 三列都不含的串必须搜不到（防「整行兜底匹配」把任何输入都判为命中）
    assert list_idle_assets(IdleQueryFilters(keyword="zzz-三列皆无")) == []


@pytest.mark.django_db
def test_sort_expire_time_asc_desc_with_null_last(account: CloudAccount) -> None:
    now = timezone.now()
    far = _make(
        account,
        resource_type="domain",
        instance_id="far.test",
        status=CloudAsset.Status.EXPIRING,
        expire_time=now + timedelta(days=20),
    )
    near = _make(
        account,
        resource_type="domain",
        instance_id="near.test",
        status=CloudAsset.Status.EXPIRING,
        expire_time=now + timedelta(days=2),
    )
    nulls = _make(
        account,
        resource_type="eip",
        instance_id="eip-null",
        status=CloudAsset.Status.UNBOUND,
        expire_time=None,
    )
    asc = [r.asset.pk for r in list_idle_assets(IdleQueryFilters(sort_field="expire_time"))]
    desc = [
        r.asset.pk
        for r in list_idle_assets(IdleQueryFilters(sort_field="expire_time", sort_order="desc"))
    ]
    assert asc == [near.pk, far.pk, nulls.pk]
    assert desc == [far.pk, near.pk, nulls.pk]  # 空值恒最后，不随升降序翻转


@pytest.mark.django_db
def test_threshold_read_from_table_per_request(account: CloudAccount) -> None:
    """spec US-4：改 `platform_setting` 不重启即生效（每请求读表）。"""
    _make(
        account,
        instance_id="i-3d",
        status=CloudAsset.Status.STOPPED,
        status_changed_at=timezone.now() - timedelta(days=3),
    )
    row = PlatformSetting.objects.get(setting_key="idle_stopped_days")
    assert row.setting_value == 14  # 迁移种子值
    assert list_idle_assets(IdleQueryFilters()) == []

    row.setting_value = 2
    row.save(update_fields=["setting_value"])
    assert _types(list_idle_assets(IdleQueryFilters())) == {IDLE_POSTPAID_STOPPED}


@pytest.mark.django_db
def test_sort_is_total_so_null_bucket_cannot_shuffle_across_pages(account: CloudAccount) -> None:
    """排序必须是**全序**：候选集 SQL 不带 ORDER BY，空值桶若不显式按 `pk` 排就随物理扫描顺序漂，
    翻页时同一批行会换序（api.md 接口16「服务端全量排序」的前提）。

    这里绕过 DB 顺序、直接喂乱序行列表，才能把这条不变量真的钉住。
    """
    verdict = IdleVerdict(IDLE_EIP_UNBOUND, "EIP 处于未绑定状态")
    now = timezone.now()
    timed = _make(
        account,
        resource_type="eip",
        instance_id="eip-timed",
        status=CloudAsset.Status.UNBOUND,
        expire_time=now + timedelta(days=1),
    )
    null_low = _make(
        account,
        resource_type="eip",
        instance_id="eip-null-low",
        status=CloudAsset.Status.UNBOUND,
        expire_time=None,
    )
    null_high = _make(
        account,
        resource_type="eip",
        instance_id="eip-null-high",
        status=CloudAsset.Status.UNBOUND,
        expire_time=None,
    )
    scrambled = [
        IdleRow(asset=a, verdict=verdict, account_name="acc1") for a in (null_high, null_low, timed)
    ]
    expected = [timed.pk, null_low.pk, null_high.pk]

    for order in ("asc", "desc"):
        out = [r.asset.pk for r in _sort_rows(scrambled, IdleQueryFilters(sort_order=order))]
        assert out == expected, order
