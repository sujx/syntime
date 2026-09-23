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
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from django.db import transaction
from django.utils import timezone

from apps.assets.models import CloudAsset
from apps.billing.models import CloudAccount

logger = logging.getLogger(__name__)

# PRD 3.13-4：域名状态由 expire_time 距今推导，不依赖导入方填写。
_EXPIRING_WITHIN_DAYS = 30


def derive_domain_status(expire_time: datetime | None, *, today: date | None = None) -> str:
    """域名状态推导（PRD 3.13-4）：>30 天正常；≤30 天即将到期；已过期；无到期时间未知。"""
    if expire_time is None:
        return CloudAsset.Status.UNKNOWN
    day = today or timezone.localdate()
    days_until = (timezone.localdate(expire_time) - day).days
    if days_until < 0:
        return CloudAsset.Status.EXPIRED
    if days_until <= _EXPIRING_WITHIN_DAYS:
        return CloudAsset.Status.EXPIRING
    return CloudAsset.Status.NORMAL


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


# ---------------------------------------------------------------------------
# 域名 CSV 导入（tasks.md 任务5 / api.md 接口14 / PRD 3.13）
#
# 语义与全量对齐（align_assets）不同：导入是增量 upsert，绝不能把本次未出现的
# 域名置 released_at（那会误删上一批导入的域名）。故单列 upsert_domain 逐行落库，
# 校验失败的行逐行回报（行号 + 原因），部分成功不整批回滚（api.md 接口14）。
# ---------------------------------------------------------------------------

# 模板列名（tasks.md 任务5）。备注列落库到 CloudAsset.remark（database.md 表10 V1.22）。
_COL_DOMAIN = "域名"
_COL_REGISTRAR = "注册商"
_COL_EXPIRE = "到期时间"
_COL_REALNAME = "实名状态"
_COL_DNS = "DNS 服务器"
_COL_DNS_ALT = "DNS服务器"
_COL_AUTO_RENEW = "自动续费"
_COL_PROJECT_TAG = "项目标签"
_COL_REMARK = "备注"

# 简单 ASCII 域名校验：标签 1~63 字符、总长 ≤253、顶级域 ≥2 位字母。
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)

# 各文本列的最大长度（与 CloudAsset 模型 max_length 对齐，超长直接判为错误行）。
_MAX_LEN: tuple[tuple[str, int], ...] = (
    (_COL_DOMAIN, 128),
    (_COL_REGISTRAR, 64),
    (_COL_REALNAME, 32),
    (_COL_DNS, 256),
    (_COL_PROJECT_TAG, 128),
)

_TRUE_TOKENS = frozenset({"是", "true", "1", "yes", "y", "t"})
_FALSE_TOKENS = frozenset({"否", "false", "0", "no", "n", "f"})

_EXPIRE_FORMATS = ("%Y/%m/%d", "%Y.%m.%d", "%Y/%m/%d %H:%M:%S")


@dataclass(frozen=True)
class DomainImportError:
    """单条失败行：CSV 行号（表头为第 1 行）+ 中文原因。"""

    row: int
    reason: str


@dataclass(frozen=True)
class DomainImportResult:
    """一次导入的结果：成功条数 + 失败行明细（部分成功不整批回滚）。"""

    success_count: int
    errors: list[DomainImportError] = field(default_factory=list)


def _clean(row: Mapping[str, object]) -> dict[str, str]:
    """规范化一行：表头与值都去首尾空白，None 视作空串。"""
    return {str(k).strip(): ("" if v is None else str(v).strip()) for k, v in row.items()}


def _get(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row:
            return row[name]
    return ""


def _parse_expire(raw: str) -> datetime | None:
    """解析到期时间：空 → None（未知状态，不算错误）；无法解析 → ValueError。"""
    if not raw:
        return None
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        for fmt in _EXPIRE_FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(raw)
    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _parse_bool(raw: str) -> bool | None:
    """解析自动续费：空 → None；是/否 及常见布尔写法 → bool；其余 → ValueError。"""
    if not raw:
        return None
    token = raw.lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    raise ValueError(raw)


def upsert_domain(
    *,
    instance_id: str,
    registrar: str | None = None,
    expire_time: datetime | None = None,
    realname_status: str | None = None,
    dns_servers: str | None = None,
    auto_renew: bool | None = None,
    project_tag: str | None = None,
    remark: str | None = None,
    today: date | None = None,
) -> tuple[CloudAsset, bool]:
    """按 uk_asset(cloud_account=NULL, 'domain', 域名) 逐行 upsert，返回 (资产, 是否新建)。

    status 一律由 expire_time 推导（PRD 3.13-4），不接受导入方填写；再导入清空
    released_at（复活）；status 变化时刷新 status_changed_at（V1.14 闲置判定口径）。
    """
    now = timezone.now()
    status = derive_domain_status(expire_time, today=today)
    asset, created = CloudAsset.objects.get_or_create(
        cloud_account=None,
        resource_type="domain",
        instance_id=instance_id,
        defaults={
            "instance_name": instance_id,
            "registrar": registrar,
            "expire_time": expire_time,
            "realname_status": realname_status,
            "dns_servers": dns_servers,
            "auto_renew": auto_renew,
            "project_tag": project_tag,
            "remark": remark,
            "status": status,
            "first_seen_at": now,
            "last_seen_at": now,
            "status_changed_at": now,
            "released_at": None,
        },
    )
    if not created:
        if asset.status != status:
            asset.status_changed_at = now
        asset.instance_name = instance_id
        asset.registrar = registrar
        asset.expire_time = expire_time
        asset.realname_status = realname_status
        asset.dns_servers = dns_servers
        asset.auto_renew = auto_renew
        asset.project_tag = project_tag
        asset.remark = remark
        asset.status = status
        asset.last_seen_at = now
        asset.released_at = None
        asset.save()
    return asset, created


def _validate(row: dict[str, str]) -> tuple[str | None, datetime | None, bool | None]:
    """校验一行，返回 (原因 or None, 到期时间, 自动续费)；命中原因即短路。"""
    domain = _get(row, _COL_DOMAIN)
    if not domain:
        return f"{_COL_DOMAIN}不能为空", None, None
    if not _DOMAIN_RE.match(domain):
        return f"{_COL_DOMAIN}格式不正确：{domain}", None, None

    try:
        expire = _parse_expire(_get(row, _COL_EXPIRE))
    except ValueError:
        return f"{_COL_EXPIRE}格式不正确：{_get(row, _COL_EXPIRE)}", None, None

    try:
        auto_renew = _parse_bool(_get(row, _COL_AUTO_RENEW))
    except ValueError:
        return (
            f"{_COL_AUTO_RENEW}取值不正确（应为 是/否）：{_get(row, _COL_AUTO_RENEW)}",
            None,
            None,
        )

    for col, limit in _MAX_LEN:
        value = _get(row, col, _COL_DNS_ALT if col == _COL_DNS else col)
        if len(value) > limit:
            return f"{col}超出长度上限（{limit}）", None, None
    return None, expire, auto_renew


def import_domains(
    rows: Iterable[Mapping[str, object]], *, today: date | None = None
) -> DomainImportResult:
    """逐行导入域名：正确行 upsert 入库，错误行逐行回报（行号 + 原因），不整批回滚。

    ``rows`` 为按模板表头取键的映射序列（csv.DictReader 产物），行号从 2 起算
    （表头为第 1 行）。备注列落库到 CloudAsset.remark（database.md 表10 V1.22）。
    """
    errors: list[DomainImportError] = []
    success = 0
    for row_num, raw in enumerate(rows, start=2):
        row = _clean(raw)
        reason, expire, auto_renew = _validate(row)
        if reason is not None:
            errors.append(DomainImportError(row=row_num, reason=reason))
            continue
        dns = _get(row, _COL_DNS, _COL_DNS_ALT)
        with transaction.atomic():
            upsert_domain(
                instance_id=_get(row, _COL_DOMAIN),
                registrar=_get(row, _COL_REGISTRAR) or None,
                expire_time=expire,
                realname_status=_get(row, _COL_REALNAME) or None,
                dns_servers=dns or None,
                auto_renew=auto_renew,
                project_tag=_get(row, _COL_PROJECT_TAG) or None,
                remark=_get(row, _COL_REMARK) or None,
                today=today,
            )
        success += 1
    return DomainImportResult(success_count=success, errors=errors)
