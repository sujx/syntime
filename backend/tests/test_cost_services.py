"""§5.3 口径计算层纯函数单测（确定性，不依赖 DB）。"""

from datetime import date
from decimal import Decimal

import pytest

from apps.cost.models import ProjectCostDaily
from apps.cost.services import (
    budget_denominator,
    budget_ratio_pct,
    covered_bill_months,
    mom_change_pct,
    previous_period,
    resolve_tag_ownership,
)

NORMAL = ProjectCostDaily.TagStatus.NORMAL
UNASSIGNED = ProjectCostDaily.TagStatus.UNASSIGNED
CONFLICT = ProjectCostDaily.TagStatus.CONFLICT


# ---------- 标签归属 PRD 2.1.1 ----------


def test_single_tag_is_normal():
    result = resolve_tag_ownership(["projA"])
    assert result.tag_status == NORMAL
    assert result.project_tag == "projA"
    assert result.is_normal


def test_no_tag_is_unassigned():
    assert resolve_tag_ownership([]).tag_status == UNASSIGNED
    assert resolve_tag_ownership([None, "", "   "]).tag_status == UNASSIGNED
    assert resolve_tag_ownership([]).project_tag is None


def test_multiple_tags_is_conflict_and_keeps_all():
    result = resolve_tag_ownership(["projA", "projB"])
    assert result.tag_status == CONFLICT
    assert result.project_tag == "projA"  # 首个，供治理定位
    assert result.raw_conflict_values == ("projA", "projB")
    assert not result.is_normal


def test_tag_values_are_stripped():
    assert resolve_tag_ownership(["  projA  "]).project_tag == "projA"


# ---------- 环比 PRD 2.2.1 ----------


def test_previous_period_equal_length_window():
    # 本期 9/5~9/18（14 天）→ 上期 8/22~9/4
    assert previous_period(date(2026, 9, 5), date(2026, 9, 18)) == (
        date(2026, 8, 22),
        date(2026, 9, 4),
    )


def test_previous_period_single_day():
    assert previous_period(date(2026, 9, 18), date(2026, 9, 18)) == (
        date(2026, 9, 17),
        date(2026, 9, 17),
    )


def test_previous_period_rejects_bad_range():
    with pytest.raises(ValueError):
        previous_period(date(2026, 9, 18), date(2026, 9, 5))


def test_mom_change_up_and_down():
    assert mom_change_pct(Decimal("120"), Decimal("100")) == Decimal("20")
    assert mom_change_pct(Decimal("80"), Decimal("100")) == Decimal("-20")


@pytest.mark.parametrize("previous", [Decimal("0"), Decimal("-50"), None])
def test_mom_change_degrades_to_none(previous):
    # 上期为 0 / 负值 / 缺失 → None（展示 --，不除零）
    assert mom_change_pct(Decimal("100"), previous) is None


def test_mom_change_current_missing_is_none():
    assert mom_change_pct(None, Decimal("100")) is None


def test_mom_change_negative_current_participates():
    # 本期负金额（退款）正常参与，PRD 2.1.2-4
    assert mom_change_pct(Decimal("-20"), Decimal("100")) == Decimal("-120")


# ---------- 预算分母 PRD 2.2.2 ----------


def test_covered_bill_months_single():
    assert covered_bill_months(date(2026, 9, 5), date(2026, 9, 18)) == ["2026-09"]


def test_covered_bill_months_cross_year():
    assert covered_bill_months(date(2025, 11, 20), date(2026, 2, 10)) == [
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
    ]


def test_covered_bill_months_rejects_bad_range():
    with pytest.raises(ValueError):
        covered_bill_months(date(2026, 9, 18), date(2026, 9, 5))


def test_budget_denominator_sums_covered_months():
    budgets = {"2026-08": Decimal("100"), "2026-09": Decimal("200")}
    denom = budget_denominator(budgets, date(2026, 8, 20), date(2026, 9, 10))
    assert denom.total == Decimal("300")
    assert denom.configured_months == ("2026-08", "2026-09")
    assert denom.unconfigured_months == ()
    assert denom.is_configured
    assert not denom.partially_unconfigured


def test_budget_denominator_missing_month_counts_zero_and_flags():
    budgets = {"2026-09": Decimal("200")}  # 8 月未配置
    denom = budget_denominator(budgets, date(2026, 8, 20), date(2026, 9, 10))
    assert denom.total == Decimal("200")
    assert denom.unconfigured_months == ("2026-08",)
    assert denom.partially_unconfigured


def test_budget_denominator_zero_amount_treated_unconfigured():
    budgets = {"2026-09": Decimal("0")}
    denom = budget_denominator(budgets, date(2026, 9, 1), date(2026, 9, 30))
    assert denom.total == Decimal("0")
    assert not denom.is_configured
    assert not denom.partially_unconfigured  # 全部未配置，非「部分」


def test_budget_ratio_normal():
    assert budget_ratio_pct(Decimal("50"), Decimal("200")) == Decimal("25")


def test_budget_ratio_over_hundred():
    assert budget_ratio_pct(Decimal("250"), Decimal("200")) == Decimal("125")


def test_budget_ratio_unconfigured_denominator_is_none():
    assert budget_ratio_pct(Decimal("50"), Decimal("0")) is None


def test_budget_ratio_current_missing_is_none():
    assert budget_ratio_pct(None, Decimal("200")) is None
