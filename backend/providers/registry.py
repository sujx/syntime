"""厂商适配器注册表（platform.md §9.6：工厂模式，按 vendor code 路由）。

任务按 cloud_account.vendor 取适配器；vendor 未注册时返回 None，由调用方
**跳过并记日志，不报错、不影响其他账号**（用例 F059）。

本期注册表只有阿里云（且消息链路受 Gate-P2a 约束）；其他厂商只留注册位与
能力矩阵扩展点，不写空壳（Q14）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from providers.base import AssetProvider, BillingProvider, MessageProvider

logger = logging.getLogger(__name__)

# 三条链路标识
LINK_BILLING = "billing"
LINK_ASSET = "asset"
LINK_MESSAGE = "message"
ALL_LINKS = (LINK_BILLING, LINK_ASSET, LINK_MESSAGE)

# 厂商能力矩阵（随代码维护的常量，不落库）：标记每个厂商支持哪些链路，
# 供任务调度与云账号配置页提示（如「该厂商暂不支持消息接收」）。
# 阿里云消息链路待 Gate-P2a C 组实测确认后启用（tasks.md §0、§9.2-4）。
VENDOR_CAPABILITIES: dict[str, frozenset[str]] = {
    "aliyun": frozenset({LINK_BILLING, LINK_ASSET}),
}


@dataclass(frozen=True)
class VendorAdapters:
    """单个厂商的三链路适配器实例（缺失的链路为 None）。"""

    vendor: str
    billing: BillingProvider | None = None
    asset: AssetProvider | None = None
    message: MessageProvider | None = None

    def get(self, link: str) -> BillingProvider | AssetProvider | MessageProvider | None:
        """按链路标识取适配器；未知链路返回 None。"""
        return getattr(self, link, None)

    def supports(self, link: str) -> bool:
        """该厂商是否已注册指定链路的适配器。"""
        return self.get(link) is not None


_REGISTRY: dict[str, VendorAdapters] = {}


def register(
    vendor: str,
    *,
    billing: BillingProvider | None = None,
    asset: AssetProvider | None = None,
    message: MessageProvider | None = None,
) -> VendorAdapters:
    """注册（或增量补全）某厂商的适配器，返回合并后的 VendorAdapters。"""
    existing = _REGISTRY.get(vendor)
    adapters = VendorAdapters(
        vendor=vendor,
        billing=billing or (existing.billing if existing else None),
        asset=asset or (existing.asset if existing else None),
        message=message or (existing.message if existing else None),
    )
    _REGISTRY[vendor] = adapters
    logger.info(
        "注册厂商适配器 vendor=%s billing=%s asset=%s message=%s",
        vendor,
        adapters.billing is not None,
        adapters.asset is not None,
        adapters.message is not None,
    )
    return adapters


def get_vendor(vendor: str) -> VendorAdapters | None:
    """取厂商适配器集合；未注册返回 None（调用方跳过并记日志，F059）。"""
    return _REGISTRY.get(vendor)


def get_provider(
    vendor: str, link: str
) -> BillingProvider | AssetProvider | MessageProvider | None:
    """取指定厂商指定链路的适配器；厂商或链路未注册返回 None。"""
    adapters = _REGISTRY.get(vendor)
    if adapters is None:
        logger.warning("厂商未注册，跳过 vendor=%s link=%s", vendor, link)
        return None
    provider = adapters.get(link)
    if provider is None:
        logger.warning("厂商链路未注册，跳过 vendor=%s link=%s", vendor, link)
    return provider


def is_registered(vendor: str) -> bool:
    """厂商是否已注册任意链路。"""
    return vendor in _REGISTRY


def registered_vendors() -> list[str]:
    """已注册厂商列表（诊断/测试用）。"""
    return sorted(_REGISTRY)


def supports_link(vendor: str, link: str) -> bool:
    """能力矩阵 + 实际注册双重判定：厂商声明支持且已注册适配器。"""
    return link in VENDOR_CAPABILITIES.get(vendor, frozenset()) and (
        get_provider(vendor, link) is not None
    )


def clear() -> None:
    """清空注册表（仅测试用）。"""
    _REGISTRY.clear()
