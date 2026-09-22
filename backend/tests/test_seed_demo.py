"""seed_demo 幂等种子测试：种入账单/资产/事件/预算并回写聚合；重复运行不翻倍不报错。"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.billing.models import CloudAccount, CloudBillDetail
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

    def test_idempotent(self):
        self._run()
        bills = CloudBillDetail.objects.count()
        accounts = CloudAccount.objects.count()
        events = CloudEvent.objects.count()
        self._run()
        self.assertEqual(CloudBillDetail.objects.count(), bills)
        self.assertEqual(CloudAccount.objects.count(), accounts)
        self.assertEqual(CloudEvent.objects.count(), events)
