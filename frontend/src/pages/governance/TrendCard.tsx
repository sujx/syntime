import { Switch } from "antd";
import { useState } from "react";
import { ChartCard } from "@/components/chart/ChartCard";
import { buildProjectTrendOption } from "@/features/charts/trendOption";
import { useTrend, type GovernanceFilters } from "@/features/governance/hooks";
import { zh } from "@/i18n/zh";
import styles from "./governance.module.css";

export function TrendCard({ filters }: { filters: GovernanceFilters }) {
  const { data } = useTrend(filters);
  const [showCompare, setShowCompare] = useState(true);
  const hasData = Boolean(
    data && data.current.length > 0 && data.current.some((p) => p.items.length > 0),
  );
  return (
    <section className={styles.card} style={{ padding: 0 }}>
      <ChartCard
        title={zh["gov.trendTitle"] ?? ""}
        extra={
          data
            ? `${data.statRange.start} ~ ${data.statRange.end}${data.billMonthIncomplete ? ` · ${zh["gov.estNote"] ?? ""}` : ""}`
            : undefined
        }
        option={hasData && data ? buildProjectTrendOption(data, showCompare) : undefined}
        height={300}
      />
      <div
        style={{
          padding: "var(--space-3) var(--space-5)",
          display: "flex",
          alignItems: "center",
          gap: "var(--space-2)",
          borderTop: "1px solid var(--gray-100)",
        }}
      >
        <Switch
          size="small"
          checked={showCompare}
          onChange={setShowCompare}
          aria-label={zh["gov.showCompare"]}
        />
        <span style={{ fontSize: 12, color: "var(--gray-600)" }}>
          {zh["gov.showCompare"] ?? ""}
        </span>
        {!hasData ? (
          <span style={{ fontSize: 12, color: "var(--gray-400)", marginLeft: "auto" }}>
            {zh["gov.empty"] ?? ""}
          </span>
        ) : null}
      </div>
    </section>
  );
}
