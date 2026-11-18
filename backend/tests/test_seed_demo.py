"""seed_demo 幂等种子测试：种入账单/资产/事件/预算并回写聚合；重复运行不翻倍不报错。"""

from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.billing.models import CloudAccount, CloudBillDetail, SyncLog
from apps.core.selectors import sync_status
from apps.cost.models import ProjectCostDaily
from apps.events.models import CloudEvent


class SeedDemoTests(TestCase):
    def _run(self) -> None:
        call_command("seed_demo", stdout=StringIO())

    def test_seeds_and_aggregates(self):
        self._run()
        self.assertEqual(CloudAccount.objects.filter(account_name="prod-main").count(), 1)
        self.assertGreater(CloudBillDetail.objects.count(), 100)
        self.assertGreaterEqual(CloudEvent.objects.count(), 3)
        self.assertGreater(ProjectCostDaily.objects.count(), 0)

    def test_seeds_dashboard_sync_sources(self):
        """仪表盘同步块两处时间都要有来源：账号字段（种子直写）+ aggregate 成功审计（种子补种）。"""
        self._run()
        status = sync_status()
        self.assertIsNotNone(status.last_aggregate_time)
        accounts = {a.account_name: a for a in status.accounts}
        self.assertIsNotNone(accounts["prod-main"].last_sync_time)
        self.assertIsNotNone(accounts["prod-edge"].last_sync_time)

    def test_aggregate_audit_not_accumulated(self):
        """重复种只留一条种子聚合审计（先清后种覆盖自身标记行）。"""
        self._run()
        self._run()
        self.assertEqual(
            AuditLog.objects.filter(action=AuditLog.Action.AGGREGATE, operator="seed_demo").count(),
            1,
        )

    def test_idempotent(self):
        self._run()
        bills = CloudBillDetail.objects.count()
        accounts = CloudAccount.objects.count()
        events = CloudEvent.objects.count()
        self._run()
        self.assertEqual(CloudBillDetail.objects.count(), bills)
        self.assertEqual(CloudAccount.objects.count(), accounts)
        self.assertEqual(CloudEvent.objects.count(), events)

    def test_idempotent_after_sync_and_detect_side_effects(self):
        """冒烟期间的失败同步日志与检测事件（非 seed: 前缀）不得让再种因 RESTRICT 报错。"""
        self._run()
        account = CloudAccount.objects.get(account_name="prod-main")
        SyncLog.objects.create(
            cloud_account=account,
            sync_type=SyncLog.SyncType.MANUAL,
            bill_date_start=date.today(),
            bill_date_end=date.today(),
            status=SyncLog.Status.FAILED,
        )
        CloudEvent.objects.create(
            event_type="budget_overrun",
            event_level=CloudEvent.EventLevel.WARNING,
            source=CloudEvent.Source.RULE,
            cloud_account=account,
            title="beat 检测残留事件",
            dedup_key="detect:leftover",
        )
        self._run()
        self.assertEqual(CloudAccount.objects.filter(account_name="prod-main").count(), 1)

    def test_idle_seed_covers_all_four_criteria(self):
        """D13：种子数据必须让四判据各能命中，且「停机不足 N 天」的行不出现。

        走真实读路径（selector），不是只看行数——种子改了 `TYPES` 后这是唯一能证明
        「闲置清单页有数据可看」的自动化检查。
        """
        from apps.assets.idle_rules import (
            IDLE_DOMAIN_EXPIRED,
            IDLE_EIP_UNBOUND,
            IDLE_POSTPAID_STOPPED,
            IDLE_PREPAID_STOPPED,
        )
        from apps.assets.selectors import IdleQueryFilters, list_idle_assets

        self._run()
        rows = list_idle_assets(IdleQueryFilters())
        self.assertEqual(
            {r.verdict.idle_type for r in rows},
            {IDLE_PREPAID_STOPPED, IDLE_POSTPAID_STOPPED, IDLE_EIP_UNBOUND, IDLE_DOMAIN_EXPIRED},
        )
        ids = {r.asset.instance_id for r in rows}
        # ①②各自点名：通用行里已经有 prepaid+stopped 与 postpaid+stopped，只断集合等于四类
        # 时删掉 `seed-prepaid-stopped` 这行样例测试仍会绿，故两条 named-sample 断言不可省。
        self.assertIn("seed-prepaid-stopped", ids)
        self.assertIn("seed-postpaid-long", ids)
        self.assertNotIn("seed-postpaid-short", ids)

    def test_seed_assets_have_timestamps(self):
        """D11 的前提：种子里的停机行必须带 `status_changed_at` 或 `first_seen_at`。"""
        from apps.assets.models import CloudAsset

        self._run()
        self.assertEqual(
            CloudAsset.objects.filter(
                status_changed_at__isnull=True, first_seen_at__isnull=True
            ).count(),
            0,
        )

    def test_seed_domains_are_reseeded_not_duplicated(self):
        """`_clean` 必须覆盖无账号的种子域名：二跑不重复，且清掉上一版遗留的孤儿行。

        **不用 pk 断言**——`_clean` 先删后种，账号行每次重种都会拿到新 pk，域名行保持 pk
        稳定不是需求。真正要钉的是「无重复」与「孤儿被清」：先插入一条本版不再写的
        `seed-domain-orphan`，3d 缺失时它会活到二跑之后。
        """
        from apps.assets.models import CloudAsset

        self._run()
        CloudAsset.objects.create(
            cloud_account=None,
            resource_type="domain",
            instance_id="seed-domain-orphan",
            instance_name="上一版遗留的域名（重种应清掉）",
        )
        self._run()
        self.assertEqual(
            CloudAsset.objects.filter(instance_id__startswith="seed-domain").count(), 2
        )
        self.assertFalse(CloudAsset.objects.filter(instance_id="seed-domain-orphan").exists())
