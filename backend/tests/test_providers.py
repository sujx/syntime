"""§5.4 适配层通用机制单测：限速 / 退避 / 凭证收口 / 客户端工厂 / 注册表（不依赖 DB）。"""

import base64
import time

import pytest

import providers.registry as registry
from apps.billing.models import CloudAccount
from common import crypto
from common.crypto import encrypt_account_credentials
from providers import base
from providers.base import (
    RateLimiter,
    RetryPolicy,
    is_throttling_error,
    rate_limited,
    resolve_credentials,
)


@pytest.fixture(autouse=True)
def _master_key(monkeypatch):
    """pytest-django 强制 DEBUG=False，dev 兜底密钥不触发；显式给固定主密钥。"""
    monkeypatch.setenv(crypto._ENV_KEY, base64.b64encode(b"p" * 32).decode())


# ---------- RateLimiter ----------


def test_rate_limiter_spaces_calls_by_min_interval():
    now = [0.0]
    slept: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(qps=2.0, clock=clock, sleep=sleep)  # 间隔 0.5s
    limiter.acquire()  # 首个不等待
    limiter.acquire()
    limiter.acquire()
    assert slept == [0.5, 0.5]


def test_rate_limiter_rejects_non_positive_qps():
    with pytest.raises(ValueError):
        RateLimiter(qps=0)


def test_from_measured_limit_applies_safety_factor():
    now = [0.0]
    limiter = RateLimiter.from_measured_limit(100.0, clock=lambda: now[0], sleep=lambda s: None)
    # 100 QPS × 0.7 = 70 QPS → 间隔 ≈ 1/70
    assert limiter._min_interval == pytest.approx(1.0 / 70.0)


# ---------- 限流错误识别 ----------


class _ThrottleErr(Exception):
    code = "Throttling.User"


class _ThrottleNested(Exception):
    code = None
    data = {"Code": "Throttling"}


class _OtherErr(Exception):
    code = "InternalError"


def test_is_throttling_error_by_code():
    assert is_throttling_error(_ThrottleErr())


def test_is_throttling_error_nested_data():
    assert is_throttling_error(_ThrottleNested())


def test_is_throttling_error_false_for_other():
    assert not is_throttling_error(_OtherErr())
    assert not is_throttling_error(ValueError("x"))


# ---------- RetryPolicy ----------


def test_retry_policy_backoff_and_cap():
    policy = RetryPolicy(base_delay=1.0, backoff_factor=2.0, max_delay=5.0)
    assert policy.delay_for(0) == 1.0
    assert policy.delay_for(1) == 2.0
    assert policy.delay_for(2) == 4.0
    assert policy.delay_for(3) == 5.0  # 封顶


# ---------- rate_limited 装饰器 ----------


def _quiet_limiter() -> RateLimiter:
    return RateLimiter(qps=1000.0, clock=time.monotonic, sleep=lambda s: None)


def test_rate_limited_retries_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    @rate_limited(_quiet_limiter(), retry=RetryPolicy(max_retries=3), sleep=slept.append)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _ThrottleErr()
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2


def test_rate_limited_gives_up_after_max_retries():
    calls = {"n": 0}

    @rate_limited(_quiet_limiter(), retry=RetryPolicy(max_retries=2), sleep=lambda s: None)
    def always_throttle() -> None:
        calls["n"] += 1
        raise _ThrottleErr()

    with pytest.raises(_ThrottleErr):
        always_throttle()
    assert calls["n"] == 3  # 1 次初始 + 2 次重试


def test_rate_limited_propagates_non_throttle_immediately():
    calls = {"n": 0}
    slept: list[float] = []

    @rate_limited(_quiet_limiter(), retry=RetryPolicy(max_retries=3), sleep=slept.append)
    def other_error() -> None:
        calls["n"] += 1
        raise _OtherErr()

    with pytest.raises(_OtherErr):
        other_error()
    assert calls["n"] == 1  # 不退避
    assert slept == []


# ---------- 凭证收口 ----------


def _account(ak: str = "LTAI-test-ak", sk: str = "test-sk") -> CloudAccount:
    ak_cipher, sk_cipher, dek_id, version = encrypt_account_credentials(ak, sk)
    return CloudAccount(
        vendor="aliyun",
        account_name="acc",
        account_type="main",
        ak_cipher=ak_cipher,
        sk_cipher=sk_cipher,
        dek_id=dek_id,
        key_version=version,
    )


def test_resolve_credentials_roundtrip():
    account = _account("LTAI-ak-1", "sk-1")
    assert resolve_credentials(account) == ("LTAI-ak-1", "sk-1")


# ---------- 客户端工厂 ----------


def test_create_client_unregistered_product_raises():
    with pytest.raises(KeyError):
        base.create_client(_account(), "nope", endpoint="ecs.cn-shanghai.aliyuncs.com")


def test_create_client_uses_supplied_class(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(base, "build_openapi_config", lambda *a, **k: sentinel)
    built: list[object] = []

    class FakeClient:
        def __init__(self, config: object) -> None:
            built.append(config)

    client = base.create_client(
        _account(), "ecs", endpoint="ecs.cn-shanghai.aliyuncs.com", client_cls=FakeClient
    )
    assert isinstance(client, FakeClient)
    assert built == [sentinel]


def test_register_product_client_routes(monkeypatch):
    monkeypatch.setattr(base, "build_openapi_config", lambda *a, **k: "cfg")

    class RdsClient:
        def __init__(self, config: object) -> None:
            self.config = config

    monkeypatch.setitem(base._PRODUCT_CLIENTS, "rds", RdsClient)
    client = base.create_client(_account(), "rds", endpoint="rds.aliyuncs.com")
    assert isinstance(client, RdsClient)


# ---------- 注册表 ----------


class _StubBilling(base.BillingProvider):
    vendor = "aliyun"

    def fetch_bills(self, account, start, end):  # noqa: D102
        return iter(())


class _StubAsset(base.AssetProvider):
    vendor = "aliyun"

    def fetch_assets(self, account, region=None):  # noqa: D102
        return iter(())


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def test_register_and_get_provider():
    stub = _StubBilling()
    registry.register("aliyun", billing=stub)
    assert registry.get_provider("aliyun", "billing") is stub
    assert registry.is_registered("aliyun")
    assert registry.registered_vendors() == ["aliyun"]


def test_get_provider_unknown_vendor_returns_none():
    assert registry.get_provider("tencent", "billing") is None
    assert registry.get_vendor("tencent") is None


def test_get_provider_unregistered_link_returns_none():
    registry.register("aliyun", billing=_StubBilling())
    assert registry.get_provider("aliyun", "asset") is None


def test_supports_link_requires_capability_and_registration():
    registry.register("aliyun", billing=_StubBilling())
    assert registry.supports_link("aliyun", "billing")
    # 消息链路：能力矩阵未声明（Gate-P2a 前）→ False
    assert not registry.supports_link("aliyun", "message")


def test_register_merges_incremental():
    registry.register("aliyun", billing=_StubBilling())
    registry.register("aliyun", asset=_StubAsset())  # 增量补全
    adapters = registry.get_vendor("aliyun")
    assert adapters is not None
    assert adapters.billing is not None
    assert adapters.asset is not None
