"""资产全量对齐服务（engineering-conventions §6 幂等：uk_asset）。

语义（database.md 表 10 / F045）：本次同步出现的实例按 uk_asset upsert；
未出现的实例置 ``released_at``（软删，可逆，不物理删除）；再次出现时清空
``released_at``。``first_seen_at`` 首次落库后不变，``last_seen_at`` 每次刷新，
``status_changed_at`` 仅在状态与库内不同步时刷新（V1.14，闲置判定口径）。

调用方（资产同步任务）负责字段映射（vendor_mapping 状态转换、标签归属、
域名扩展字段），传入已组装好的未保存 ``CloudAsset`` 实例；本函数只管对齐幂等。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.assets.models import CloudAsset
from apps.billing.models import CloudAccount

logger = logging.getLogger(__name__)

_UK_ASSET_FIELDS = ["cloud_account", "resource_type", "instance_id"]
_ASSET_UPDATE_FIELDS = [
    "region",
    "instance_name",
    "project_tag",
    "raw_tags",
    "status",
    "vendor_status",
    "status_changed_at",
    "spec",
    "private_ip",
    "public_ip",
    "charge_type",
    "expire_time",
    "registrar",
    "realname_status",
    "dns_servers",
    "auto_renew",
    "first_seen_at",
    "last_seen_at",
    "released_at",
    "update_time",
]

_AssetKey = tuple[str, str]


@dataclass(frozen=True)
class AlignResult:
    """一次全量对齐的结果计数。"""

    upserted: int
    released: int


def align_assets(account: CloudAccount | None, assets: Iterable[CloudAsset]) -> AlignResult:
    """全量对齐：出现者 upsert，缺席者置 ``released_at``（软删）。

    ``account`` 传 None 表示对齐无归属云账号的资产（域名等）；传入实例的
    ``cloud_account`` 必须与之一致（调用方保证，不逐行校验）。
    """
    now = timezone.now()
    incoming = list(assets)
    incoming_keys = {(a.resource_type, a.instance_id) for a in incoming}

    with transaction.atomic():
        existing_rows = CloudAsset.objects.filter(cloud_account=account).only(
            "id",
            "resource_type",
            "instance_id",
            "status",
            "status_changed_at",
            "first_seen_at",
        )
        existing: dict[_AssetKey, tuple[int, str, datetime | None, datetime | None]] = {
            (r.resource_type, r.instance_id): (
                r.pk,
                r.status,
                r.status_changed_at,
                r.first_seen_at,
            )
            for r in existing_rows
        }

        for asset in incoming:
            old = existing.get((asset.resource_type, asset.instance_id))
            if old is None:
                asset.first_seen_at = now
                asset.status_changed_at = now
            else:
                _, old_status, old_status_changed_at, old_first_seen = old
                asset.first_seen_at = old_first_seen
                asset.status_changed_at = (
                    now if asset.status != old_status else old_status_changed_at
                )
            asset.last_seen_at = now
            asset.released_at = None  # 重新出现（曾释放）则复活

        if incoming:
            CloudAsset.objects.bulk_create(
                incoming,
                update_conflicts=True,
                update_fields=_ASSET_UPDATE_FIELDS,
                unique_fields=_UK_ASSET_FIELDS,
            )

        # 缺席者置 released_at：只标记一次，重复对齐不刷新释放时间（可追溯）
        unseen_pks = [pk for (key, (pk, *_)) in existing.items() if key not in incoming_keys]
        released = (
            CloudAsset.objects.filter(pk__in=unseen_pks, released_at__isnull=True).update(
                released_at=now
            )
            if unseen_pks
            else 0
        )

    return AlignResult(upserted=len(incoming), released=released)
