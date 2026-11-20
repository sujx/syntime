"""闲置清单读路径（api.md 接口16）：谓词下推的 SQL 形状、判定、过滤、排序、每请求读配置。"""

from __future__ import annotations

from dataclasses import fields
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.assets.idle_rules import (
    IDLE_DOMAIN_EXPIRED,
    IDLE_EIP_UNBOUND,
    IDLE_POSTPAID_STOPPED,
    IDLE_PREPAID_STOPPED,
)
from apps.assets.models import CloudAsset
from apps.assets.selectors import (
    _PROJECTION,
    _SORTABLE,
    _TEXT_SORT_KEYS,
    IdleCandidate,
    IdleQueryFilters,
    list_idle_assets,
    prepare_idle_read,
)
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
def test_sql_carries_the_exact_predicate_not_a_prefilter() -> None:
    """读路径的 SQL 必须自己带完整判定谓词：`charge_type` 比较与三级回退都在 WHERE 里。

    取代删除的 `test_candidate_prefilter_is_lossless`（D14-g）。这条**不证明等价**
    （等价归 `test_idle_sql_equiv.py`），它证明的是**位置**：判定确实进了 SQL，
    而不是整份取回 4 万候选行后再在 Python 里筛。`stopped` 出现两次是新旧形状的分界——
    旧预筛只在一个 `status IN (…)` 里写它 1 次，新 SQL 里判据 ① 与 ② 各自比较一次。

    token 写法按 Django 5.2 的现证渲染定稿：`str(query)` 走 `sql % params`，字面量
    **裸内联不带引号**（`"cloud_asset"."status" = stopped`），故这里先去单引号再比对，
    使断言对「裸值」与「带引号值」两种渲染同时成立，而**计数**仍是硬约束。
    """
    _make(None, resource_type="eip", instance_id="shape-1", status=CloudAsset.Status.UNBOUND)
    sql = str(prepare_idle_read(IdleQueryFilters()).queryset.query).replace("'", "")
    assert "COALESCE(" in sql  # ② 的 D11 三级回退进了 SQL，不是在 Python 里回退
    assert sql.count("= stopped") == 2  # ①② 各一次；旧预筛只在 IN (…) 里写 1 次
    assert "= prepaid" in sql and "= postpaid" in sql  # 旧形状根本不读 charge_type
    for tok in ("= eip", "= unbound", "= domain", "IN (expired, expiring)"):
        assert tok in sql  # ③④ 两支的取值也必须逐支落在 WHERE 里，不能只靠取回后再筛


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
def test_stopped_since_fallback_hits_criterion_2_through_the_read_path(
    account: CloudAccount,
) -> None:
    """D11 三级回退必须**穿过 DB 读路径**命中判据 ②（spec §8-D11 / 终审 IM-1）。

    **这条在防什么（它存在的全部理由）**：防「停机 ≥ N 天」的日阈值下推进 SQL 时**只按第 1 级
    取值**——即给 `idle_predicate_sql()` 加一条 `status_changed_at__lte=now -
    timedelta(days=N)`，而不是挂在 `IDLE_SINCE` 那三级 `COALESCE` 注解上（spec §8-D12 当年
    因此禁止下推日阈值；Task 2 把判定整体下推后，本条就是「下推的写法没丢回退」的唯一现场证据）。
    只要那条下推按**当前阈值**取数（而不是把 14 写死），其余旧测试实测全绿，而它会
    **静默丢掉所有停机起点来自回退的行**：这两行的 `status_changed_at` 在库里都是 NULL，
    `stopped_since`（`idle_rules.py`）只能落到 `first_seen_at` / `create_time`，而按
    `status_changed_at` 过滤的 SQL 谓词对 NULL 恒为假 ⇒ 行在进 `judge` 之前就被挡掉。
    所以断言必须打在 `list_idle_assets` 上，而不是像
    `tests/test_idle_rules.py::test_stopped_since_three_level_fallback` 那样只在未保存实例上
    打口径层——后者挡不住这次下推。

    这是活路径不是理论路径：`apps/assets/services.py` 的 `align_assets` 对状态未变的行
    保留旧 `status_changed_at`（历史行为 NULL ⇒ 落到 `first_seen_at`）。
    """
    now = timezone.now()
    # 回退第二级：status_changed_at 为空，靠 first_seen_at 拿到 20 天
    by_first_seen = _make(
        account,
        charge_type="postpaid",
        status=CloudAsset.Status.STOPPED,
        status_changed_at=None,
        first_seen_at=now - timedelta(days=20),
    )
    # 回退第三级：`create_time` 是 `auto_now_add`，insert 后只能用 queryset 改写；
    # `status_changed_at` 与 `first_seen_at` 保持 NULL（`_make` 默认不写这两列），
    # 否则判据 ② 会在前两级就取到值，第三级等于没测。
    by_create_time = _make(account, charge_type="postpaid", status=CloudAsset.Status.STOPPED)
    CloudAsset.objects.filter(pk=by_create_time.pk).update(create_time=now - timedelta(days=25))

    rows = list_idle_assets(IdleQueryFilters())
    by_pk = {r.asset.pk: r for r in rows}
    assert set(by_pk) == {by_first_seen.pk, by_create_time.pk}  # 少一行即回退层级被 SQL 挡掉
    assert list(
        CloudAsset.objects.filter(pk__in=by_pk).values_list("status_changed_at", flat=True)
    ) == [None, None]  # 命中的两行确实没有 status_changed_at 可用

    for pk, stopped_days in ((by_first_seen.pk, 20), (by_create_time.pk, 25)):
        verdict = by_pk[pk].verdict
        assert verdict.idle_type == IDLE_POSTPAID_STOPPED
        # thresholdDays=14：`platform_setting.idle_stopped_days` 的迁移种子值（见上面阈值测试）
        assert verdict.key_metric == {"stoppedDays": stopped_days, "thresholdDays": 14}


@pytest.mark.django_db
def test_sql_order_is_total_and_pages_stitch_without_overlap(account: CloudAccount) -> None:
    """排序全序性从 Python 侧那份全量排序搬到 SQL：跨页拼接不重、不漏、不换序（D14-d）。

    三点同时成立才放行：空值桶恒最后（不随方向翻转）、同值行的次级键**跟随**方向
    （`asc` ⇒ pk ASC、`desc` ⇒ pk DESC）、空值桶恒 pk ASC。把次级键写成无条件 `-pk`
    的形状在 `asc` 档必然红——那正是 spec D14-d 点名的错法。第三条只有空值桶里**放着
    两行**才有牙：单行时那支 `then` 无论写成 `F("id")` 还是 `-F("id")` 取回的都是同一行，
    所以这里两档都断言空值桶按 pk ASC 出现（把 `then=F("id")` 翻成 `-F("id")` ⇒ 两档同红）。

    各行 pk 由 `_make` 走 `CloudAsset.objects.create` 顺序落库 ⇒ 单调递增（pk 来自
    `DEFAULT_AUTO_FIELD = BigAutoField` 的序列，创建顺序即 pk 顺序；`instance_id` 里那个计数
    只保证列值唯一，不是 pk 单调的原因）；这是本条期望序列成立的前提，若改用 bulk_create
    之类无序写法就要同步改期望。
    """
    same_tag = [
        _make(
            account,
            resource_type="eip",
            instance_id=f"tie-{i}",
            status=CloudAsset.Status.UNBOUND,
            project_tag="同值",
        )
        for i in range(3)
    ]
    null_tag = [
        _make(
            account,
            resource_type="eip",
            instance_id=f"tie-null-{i}",
            status=CloudAsset.Status.UNBOUND,
            project_tag=None,
        )
        for i in range(2)
    ]
    null_pks = [a.pk for a in null_tag]  # 空值桶恒 pk ASC，与 sort_order 无关
    expected = {
        "asc": [a.pk for a in same_tag] + null_pks,
        "desc": [a.pk for a in reversed(same_tag)] + null_pks,
    }
    for order in ("asc", "desc"):
        filters = IdleQueryFilters(sort_field="project_tag", sort_order=order)
        read = prepare_idle_read(filters)
        stitched = [
            row.asset.pk
            for page in range(5)  # 每页 1 行 × 5 页 = 5 行全覆盖（切片偏移 0..4 各命中一行）
            for row in read.rows(list(read.queryset[page : page + 1]))
        ]
        assert stitched == expected[order], order


@pytest.mark.django_db
def test_text_sort_uses_binary_collation(account: CloudAccount) -> None:
    """文本键排序必须带 `COLLATE "C"` ＋ `NULLS LAST`（D14-f/D14-d）。

    本机 `datcollate=en_HK.UTF-8` 与 Python 码位序不同；collation 一变，`LIMIT 20`
    取到的是**另一批行**，不是「顺序难看」的小事。
    """
    _make(account, resource_type="eip", instance_id="col-1", status=CloudAsset.Status.UNBOUND)
    sql = str(prepare_idle_read(IdleQueryFilters(sort_field="instance_id")).queryset.query)
    assert 'COLLATE "C"' in sql
    assert "NULLS LAST" in sql


@pytest.mark.django_db
def test_collate_c_beats_locale_order_on_mixed_case(account: CloudAccount) -> None:
    """大小写＋非 ASCII 混合 ID：码位序 `B` < `a` < `中`，`en_HK` 下大写与重音次序不同。

    这条是上一条的**结果版**：上一条只看 SQL 文本，这一条真的让 DB 排序并取前两行。

    创建顺序刻意让 `a-eip` 先落库（＝locale 序，也＝没有 ORDER BY 时的物理取回序），期望
    却是 `B-eip` 在前 ⇒「压根没排序」和「按 locale 排序」两种退化都当场红，只有
    `COLLATE "C"` 能绿（现证见 task-3 报告「Fix round 1」的两次变异）。
    """
    _make(account, resource_type="eip", instance_id="a-eip", status=CloudAsset.Status.UNBOUND)
    _make(account, resource_type="eip", instance_id="B-eip", status=CloudAsset.Status.UNBOUND)
    _make(account, resource_type="eip", instance_id="中文-eip", status=CloudAsset.Status.UNBOUND)
    read = prepare_idle_read(IdleQueryFilters(sort_field="instance_id"))
    ids = [row.asset.instance_id for row in read.rows(list(read.queryset[:2]))]
    assert ids == ["B-eip", "a-eip"]  # 码位序：ASCII 大写在前，非 ASCII 排最后


def test_text_sort_key_set_covers_every_char_field() -> None:
    """`_SORTABLE` 里每个 CharField 都必须落在 `_TEXT_SORT_KEYS` 里（D14-f 覆盖面，全序键不遗漏）。

    其它用例只真的执行过 `instance_id`/`project_tag`/`expire_time` 三键：`region`、`status`、
    `resource_type` 一旦从 frozenset 里掉出去，全套件仍全绿，而它们会静默退回 locale 序
    ⇒ `LIMIT` 取回的是另一批行。这里用模型元数据把覆盖面钉成集合包含关系，不建任何行。
    """
    char_keys = {
        name
        for name in _SORTABLE
        if CloudAsset._meta.get_field(name).get_internal_type() == "CharField"
    }
    assert char_keys <= _TEXT_SORT_KEYS


@pytest.mark.django_db
def test_account_name_resolved_without_joining_account_per_row(account: CloudAccount) -> None:
    """候选扫描**不 JOIN** 账号表，归属账号名另由一次独立读取解析（规格 §8.1 方案 5）。

    5 万行实测里 `select_related("cloud_account")` 把账号表的列复制到 40012 行候选上，
    仅去掉这一 JOIN 就省 **662ms**（1911→1249，规格 §8.1「瓶颈定位」对照③）。耗时不进
    pytest（D12 口径：一次性脚本实测），但 JOIN 一旦被加回来，`" JOIN "` 断言必然当场红。
    """
    _make(
        account,
        instance_id="i-no-join",
        status=CloudAsset.Status.STOPPED,
        status_changed_at=timezone.now() - timedelta(days=20),
    )
    with CaptureQueriesContext(connection) as ctx:
        rows = list_idle_assets(IdleQueryFilters())
    assert [r.account_name for r in rows] == ["acc1"]  # 降本不得改变结果
    assert [q["sql"] for q in ctx.captured_queries if " JOIN " in q["sql"]] == []


@pytest.mark.django_db
def test_account_name_three_states_survive_the_dict_read(account: CloudAccount) -> None:
    """去 JOIN 后归属解析三态不变：有账号取名、账号为空取 None、域名恒取注册商。

    第三态是 PRD 3.14-2 的产品规则本身，此前只写在 `_account_name` 的 docstring 里、没有
    用例覆盖「域名行**挂了**账号」这一组合——字典化改造最容易在这里把注册商读丢。
    """
    owned = _make(
        account, resource_type="eip", instance_id="eip-owned", status=CloudAsset.Status.UNBOUND
    )
    orphan = _make(
        None, resource_type="eip", instance_id="eip-orphan", status=CloudAsset.Status.UNBOUND
    )
    domain = _make(
        account,
        resource_type="domain",
        instance_id="d.test",
        status=CloudAsset.Status.EXPIRING,
        expire_time=timezone.now() + timedelta(days=7),
        registrar="注册商甲",
    )
    names = {r.asset.pk: r.account_name for r in list_idle_assets(IdleQueryFilters())}
    assert names == {owned.pk: "acc1", orphan.pk: None, domain.pk: "注册商甲"}


@pytest.mark.django_db
def test_account_names_are_read_once_not_per_row(account: CloudAccount) -> None:
    """命中行跨 3 个账号共 9 行时，提到 `cloud_account` 的语句仍只有 **1 条**。

    这条钉的是另一种「去 JOIN 但逐行 `asset.cloud_account`」的实现形态：那时 SQL 里没有
    JOIN、上一条测试全绿，代价变成每行一条懒加载查询。
    """
    accounts = [account]
    for i in (2, 3):
        accounts.append(
            CloudAccount.objects.create(
                vendor="tencent",
                account_name=f"acc-{i}",
                account_type="sub",
                ak_cipher="x",
                sk_cipher="y",
            )
        )
    for n in range(9):
        _make(
            accounts[n % 3],
            resource_type="eip",
            instance_id=f"eip-{n}",
            status=CloudAsset.Status.UNBOUND,
        )
    with CaptureQueriesContext(connection) as ctx:
        rows = list_idle_assets(IdleQueryFilters())
    assert len(rows) == 9
    assert {r.account_name for r in rows} == {"acc1", "acc-2", "acc-3"}
    account_queries = [q["sql"] for q in ctx.captured_queries if '"cloud_account"' in q["sql"]]
    assert len(account_queries) == 1


@pytest.mark.django_db
def test_read_path_yields_projection_rows_not_model_instances(account: CloudAccount) -> None:
    """读路径取回的是**投影行**而非 `CloudAsset` 模型对象（规格 §8.1 方案 3）。

    历史读数（保留为带日期的史实，量的都是**整表取回**那一档）：2026-11-18 5 万行实测——同一
    候选集下不建模型对象的投影取回 **624ms** vs 整行模型对象 **1911ms**，且这一降本在并发下
    同样成立（并发档 P95 **3016 → 1907**，规格 §8.2 同一并发档的两个读数；`3016` 是表内自注的
    **改动前另一次运行** ⇒ 这一对不是同轮双臂；`1772` 的原始记录在 CHANGELOG V1.49 ②，是
    **进程内**读数，量测单元与「5 进程并发」不同，2026-11-20 最终审查后撤销它与 3016 的误配）；
    2026-11-19 在部署形态
    （gunicorn ＋ 真 HTTP）复测同一形状的 5 并发 P95 = **2808ms**（规格 §8.3；门槛口径是
    5 并发 P95 ≤ 2000ms）。2026-11-20 记录的新事实：谓词＋排序＋分页下推后（2026-11-19 落地），
    接口 16 的视图每请求只取回一页、只构造页内的行对象，上面那几个整表档读数不再是视图的代价
    （视图档的同轮读数统一记在 `apps/assets/selectors.py` 的模块 docstring，别在这里抄一份）。

    所以本条钉的是**取回形状**，不是性能证据；耗时不进 pytest（D12 口径）。但形状一旦被改回
    整行取回，本条必然红：四判据/序列化/API 的所有既有断言都是属性级的，模型对象与投影行都能
    满足，**唯有形状本身需要单独钉住**。
    """
    made = [
        _make(
            account,
            instance_id=f"i-proj-{n}",
            instance_name="投影名称",
            region="cn-shanghai",
            project_tag="投影项目",
            resource_type="eip",
            status=CloudAsset.Status.UNBOUND,
        )
        for n in range(2)
    ]
    rows = list_idle_assets(IdleQueryFilters(resource_type="eip"))
    assert len(rows) == 2
    assert not any(isinstance(row.asset, CloudAsset) for row in rows)
    assert all(isinstance(row.asset, IdleCandidate) for row in rows)
    # 形状换了，出参一个字段都不能变（序列化层与判据读的都是属性）
    assert [(r.asset.pk, r.asset.instance_name, r.asset.region) for r in rows] == [
        (m.pk, "投影名称", "cn-shanghai") for m in made
    ]
    assert [r.account_name for r in rows] == ["acc1", "acc1"]
    assert {r.verdict.idle_type for r in rows} == {IDLE_EIP_UNBOUND}


@pytest.mark.django_db
def test_projection_columns_are_the_row_fields_in_order(account: CloudAccount) -> None:
    """`_PROJECTION` 与 `IdleCandidate` 字段**同名同序**——投影是位置构造，错一列就串一列值。

    `IdleCandidate(*t)` 按位置吃 `values_list` 的元组，列名与字段名之间没有编译器可查的绑定；
    本条把这条绑定钉成测试，任何一侧单独改动都会红。域名归属用的 `registrar` 也在此列内
    （PRD 3.14-2），漏掉它不会在别处报错，只会让 `account_name` 静默变 None。
    """
    assert _PROJECTION == tuple(f.name for f in fields(IdleCandidate))
    assert set(_PROJECTION) >= {
        "released_at",
        "status_changed_at",
        "first_seen_at",
        "create_time",
        "expire_time",
        "charge_type",
        "status",
        "resource_type",
        "instance_id",
        "instance_name",
        "region",
        "project_tag",
        "registrar",
        "cloud_account_id",
    }
