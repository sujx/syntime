"""多厂商适配层抽象（platform.md §9.6、engineering-conventions §5.4 / §9.2）。

本模块是「取数 + 转标准结构」的契约与通用机制，**不含任何厂商实现与业务判断**：

- 数据契约：BillLine / AssetRecord / VendorMessage —— 适配器产出的标准结构；
- 抽象接口：BillingProvider / AssetProvider / MessageProvider —— 三条链路；
- 通用限速（§5.4）：RateLimiter + rate_limited 装饰器，按实测限流阈值 70% 配置，
  识别 Throttling 错误码并指数退避；各适配器不得自建节流（§9.2-7）；
- 凭证与客户端收口（§9.2-5/6/9）：resolve_credentials 集中解密 AK/SK，
  create_client 是唯一构造入口（统一超时、关闭 SDK 自动重试），密钥轮换在此收口。

标签归属、事件级别、聚合判断一律在平台侧（apps/），适配器内出现业务判断视为评审不通过。
SDK 相关构造（tea_openapi.Config / RuntimeOptions）走**懒加载**——阿里云实现受 Gate-P2a
约束（tasks.md §0），抽象层先行落地，实测前不导入任何 alibabacloud_* 包。
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:  # 仅类型标注，运行期不耦合 apps（避免 import 环）
    from apps.billing.models import CloudAccount

logger = logging.getLogger(__name__)

# 限速安全系数：按实测限流阈值的 70% 配置（坑点清单验收标准 9 / §5.4）
RATE_SAFETY_FACTOR = 0.7


# ---------- 数据契约（标准结构） ----------


@dataclass(frozen=True)
class BillLine:
    """账单明细标准结构（落库前由 apps/billing/services.py 折算 + 判标签归属）。

    resource_type / charge_type / region 为**平台标准值**（适配器经 vendor_mapping 转换）；
    金额保留原币与币种，折算（amount_cny = amount × exchange_rate）在平台导入层完成。
    标签不在适配器解析：raw_tags 原样带出，归属判定在平台侧（§9.6 职责边界）。
    """

    bill_date: date
    resource_type: str
    charge_type: str
    currency: str
    amount: Decimal
    instance_id: str | None = None
    region: str | None = None
    raw_tags: str | None = None
    # 厂商原始值追溯（vendor_resource_type / vendor_charge_type 等），不落业务列
    vendor_raw: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetRecord:
    """资产标准结构（落 cloud_asset 前由平台侧判标签归属与到期状态推导）。"""

    instance_id: str
    resource_type: str
    # 平台标准状态：running/stopped/bound/unbound/normal/abnormal/expiring/expired/unknown
    status: str
    region: str | None = None
    instance_name: str | None = None
    charge_type: str | None = None
    vendor_status: str | None = None  # 厂商原始状态，未识别时原样保留（PRD 3.11-3）
    spec: str | None = None
    private_ip: str | None = None
    public_ip: str | None = None
    expire_time: datetime | None = None
    raw_tags: str | None = None
    # 域名等扩展字段（registrar/realname_status/dns_servers/auto_renew）走 extra
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VendorMessage:
    """厂商消息标准结构（事件类型映射在平台侧，经 vendor_mapping）。"""

    message_id: str
    raw_payload: str
    vendor_event_code: str | None = None
    vendor_event_name: str | None = None
    occurred_at: datetime | None = None  # 厂商发生时间（与平台 received_at 分离，PRD 3.12-8.1）
    region: str | None = None
    resource_id: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


# ---------- 三条链路抽象接口 ----------


class BillingProvider(ABC):
    """账单链路：拉取账单明细并转标准结构。"""

    vendor: ClassVar[str]

    @abstractmethod
    def fetch_bills(self, account: CloudAccount, start: date, end: date) -> Iterator[BillLine]:
        """拉取 [start, end] 账期明细；只读，分页/限速由适配器内部处理。"""


class AssetProvider(ABC):
    """资产链路：拉取云资源台账并转标准结构。"""

    vendor: ClassVar[str]

    @abstractmethod
    def fetch_assets(
        self, account: CloudAccount, region: str | None = None
    ) -> Iterator[AssetRecord]:
        """全量拉取资产快照；本次未出现的实例由平台侧置 released_at（软删）。"""


class MessageProvider(ABC):
    """消息链路：拉取厂商消息/事件并转标准结构。"""

    vendor: ClassVar[str]

    @abstractmethod
    def fetch_messages(self, account: CloudAccount, since: datetime) -> Iterator[VendorMessage]:
        """拉取 since 之后的消息；未识别消息由平台侧全量落 vendor_message_log（Q12）。"""


# ---------- 通用限速（§5.4） ----------

# 阿里云限流错误码（§9.2-7：Throttling / Throttling.User 必须被识别并退避）
THROTTLING_ERROR_CODES = frozenset(
    {
        "Throttling",
        "Throttling.User",
        "Throttling.Api",
        "FlowLimit",
        "FlowLimit.User",
    }
)


def is_throttling_error(exc: BaseException) -> bool:
    """判断异常是否为厂商限流错误（按错误码， Tea SDK 错误带 .code 属性）。"""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code in THROTTLING_ERROR_CODES:
        return True
    # 兜底：部分 SDK 把 code 放在 data/args 里
    data = getattr(exc, "data", None)
    if isinstance(data, Mapping):
        nested = data.get("Code") or data.get("code")
        if isinstance(nested, str) and nested in THROTTLING_ERROR_CODES:
            return True
    return False


@dataclass(frozen=True)
class RetryPolicy:
    """限速层退避策略（与 §5.1 Celery 任务级重试分层，互不叠加，§9.2-7）。"""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0

    def delay_for(self, attempt: int) -> float:
        """第 attempt 次（0 起）退避秒数，封顶 max_delay。"""
        return min(self.max_delay, self.base_delay * self.backoff_factor**attempt)


class RateLimiter:
    """进程内最小间隔节流器（线程安全）。

    跨进程互斥由 §5.1 任务锁保证（同账号同时只一个同步任务），故本地节流即可。
    qps 应取实测限流阈值 × RATE_SAFETY_FACTOR（见 from_measured_limit）。
    clock / sleep 可注入，便于确定性单测。
    """

    def __init__(
        self,
        qps: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if qps <= 0:
            raise ValueError("qps 必须为正数")
        self._min_interval = 1.0 / qps
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_slot = clock()

    @classmethod
    def from_measured_limit(
        cls,
        limit_qps: float,
        *,
        safety: float = RATE_SAFETY_FACTOR,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> RateLimiter:
        """按实测限流阈值的安全比例（默认 70%）构造节流器（§5.4 验收标准 9）。"""
        return cls(limit_qps * safety, clock=clock, sleep=sleep)

    def acquire(self) -> None:
        """阻塞至下一个可用时间槽，保证相邻调用间隔 ≥ 1/qps。"""
        with self._lock:
            now = self._clock()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._min_interval
        if wait > 0:
            self._sleep(wait)


def rate_limited(
    limiter: RateLimiter,
    *,
    retry: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """限速装饰器：调用前节流，遇限流错误指数退避重试（§5.4 / §9.2-7）。

    非限流异常立即抛出（交 §5.1 Celery 任务级重试处理，分层不叠加）。
    """
    policy = retry or RetryPolicy()

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            while True:
                limiter.acquire()
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 - 仅对限流错误退避，其余原样抛
                    if not is_throttling_error(exc) or attempt >= policy.max_retries:
                        raise
                    delay = policy.delay_for(attempt)
                    logger.warning(
                        "限流退避 fn=%s attempt=%d delay=%.2fs", fn.__name__, attempt, delay
                    )
                    sleep(delay)
                    attempt += 1

        return wrapper

    return decorator


# ---------- 凭证与客户端收口（§9.2-5/6/9） ----------


def resolve_credentials(account: CloudAccount) -> tuple[str, str]:
    """从云账号解密 AK/SK（信封加密，common.crypto）——密钥轮换的唯一收口点。

    业务代码与适配器方法内禁止直接读密文或自行解密（§9.2-5）。
    """
    from common.crypto import decrypt_account_credentials

    if account.dek_id is None:
        raise ValueError(
            f"云账号 {account.account_name} 缺少 dek_id，无法解密凭证（请先加密录入 AK/SK）"
        )
    return decrypt_account_credentials(
        account.ak_cipher,
        account.sk_cipher,
        dek_id=account.dek_id,
        key_version=account.key_version,
    )


def default_runtime_options(*, connect_timeout_ms: int = 5000, read_timeout_ms: int = 10000) -> Any:
    """构造 tea_util RuntimeOptions：显式超时 + 关闭 SDK 自动重试（§9.2-7/9）。

    懒加载 alibabacloud_tea_util——阿里云实现受 Gate-P2a 约束，抽象层不预导入 SDK。
    """
    from alibabacloud_tea_util.models import RuntimeOptions  # type: ignore[import-not-found]

    return RuntimeOptions(
        connect_timeout=connect_timeout_ms,
        read_timeout=read_timeout_ms,
        autoretry=False,  # 瞬时错误交限速层退避 + Celery 任务级重试，三层不叠加
        max_attempts=0,
    )


def build_openapi_config(account: CloudAccount, *, endpoint: str, region: str | None = None) -> Any:
    """构造 tea_openapi Config：解密凭证 + 显式 endpoint/region（§9.2-5/6）。

    endpoint 由厂商适配器解析后传入（账单/域名中心化、实例类按 region 寻址），
    base 不内置任何厂商 endpoint 表，保持厂商无关。
    """
    from alibabacloud_tea_openapi import models as open_api_models  # type: ignore[import-not-found]

    ak, sk = resolve_credentials(account)
    config = open_api_models.Config(
        access_key_id=ak,
        access_key_secret=sk,
        endpoint=endpoint,
    )
    if region is not None:
        config.region_id = region
    return config


# 产品 → 客户端类注册表（由各厂商适配器在实现落地时注册；Gate-P2a 前为空）
_PRODUCT_CLIENTS: dict[str, type] = {}


def register_product_client(product: str, client_cls: type) -> None:
    """注册产品客户端类，供 create_client 按 product 路由（厂商适配器调用）。"""
    _PRODUCT_CLIENTS[product] = client_cls


def create_client(
    account: CloudAccount,
    product: str,
    *,
    endpoint: str,
    region: str | None = None,
    client_cls: type | None = None,
) -> Any:
    """客户端构造唯一入口（§9.2-5）：集中解密凭证 + 统一超时策略。

    client_cls 缺省时按 product 从注册表取；未注册抛 KeyError（提示适配器先注册）。
    业务代码与适配器方法内禁止直接 new Client，否则密钥轮换无法统一收口。
    """
    cls = client_cls or _PRODUCT_CLIENTS.get(product)
    if cls is None:
        raise KeyError(f"产品客户端未注册：product={product}（适配器应先 register_product_client）")
    config = build_openapi_config(account, endpoint=endpoint, region=region)
    return cls(config)
