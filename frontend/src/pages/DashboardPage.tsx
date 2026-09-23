import { Button, Empty, Skeleton } from "antd";
import type { ReactNode } from "react";
import { ChartCard } from "@/components/chart/ChartCard";
import { useDashboard } from "@/features/dashboard/hooks";
import { buildResourceTrendOption } from "@/features/charts/trendOption";
import { useAuth } from "@/hooks/useAuth";
import { zh } from "@/i18n/zh";
import styles from "./dashboard/dashboard.module.css";
import { formatDateTime } from "@/utils/datetime";

export default function DashboardPage() {
  const { username } = useAuth();
  const { data, isPending, isError, refetch } = useDashboard();

  return (
    <div data-testid="page-dashboard">
      <h1 className="page-title" style={{ marginBottom: "var(--space-5)" }}>
        {zh["nav.dashboard"]}
        {username ? (
          <span
            style={{
              fontSize: 13,
              fontWeight: 400,
              color: "var(--gray-500)",
              marginLeft: "var(--space-3)",
            }}
          >
            {username}
          </span>
        ) : null}
      </h1>
      {isPending ? <Skeleton active paragraph={{ rows: 8 }} /> : null}
      {isError && !data ? (
        <Empty description={zh["common.loadFail"]}>
          <Button autoInsertSpace={false} onClick={() => void refetch()}>
            {zh["common.retry"]}
          </Button>
        </Empty>
      ) : null}
      {data ? (
        <>
          <div className={styles.kpiGrid}>
            <Kpi
              label={zh["dash.kpiCloud"] ?? ""}
              value={data.cards.cloudAccountTotal}
              sub={`${zh["dash.enabled"]} ${data.cards.enabled} · ${zh["dash.disabled"]} ${data.cards.disabled}`}
            />
            <Kpi
              label={zh["dash.kpiAsset"] ?? ""}
              value={data.cards.assetTotal}
              sub={`${zh["dash.running"]} ${data.cards.running} · ${zh["dash.stopped"]} ${data.cards.stopped}`}
            />
            <Kpi
              label={zh["dash.kpiMonth"] ?? ""}
              value={data.cards.monthAmount}
              sub={
                <>
                  <span
                    className={`${styles.pill} ${data.cards.monthRate === "--" ? styles.neutral : Number(data.cards.monthRate) >= 0 ? styles.up : styles.down}`}
                  >
                    {data.cards.monthRate === "--"
                      ? "--"
                      : `${Number(data.cards.monthRate) >= 0 ? "↑" : "↓"} ${data.cards.monthRate}%`}
                  </span>
                  {data.cards.isEstimate ? (
                    <span className={`${styles.pill} ${styles.neutral}`}>
                      {zh["dash.estimateTag"]}
                    </span>
                  ) : null}
                </>
              }
            />
            <Kpi
              label={zh["dash.kpiUnallocated"] ?? ""}
              value={data.cards.unallocatedAmount}
              sub={`${zh["dash.ratio"]} ${data.cards.unallocatedRatio}%`}
            />
            <Kpi
              label={zh["dash.kpiEvent"] ?? ""}
              value={data.cards.eventPending}
              sub={`${zh["dash.high"]} ${data.cards.eventHigh} · ${zh["dash.warning"]} ${data.cards.eventWarning}`}
            />
          </div>
          <div className={styles.cols}>
            <ChartCard
              title={zh["dash.trendTitle"] ?? ""}
              extra={zh["dash.trendExtra"]}
              emptyText={zh["gov.empty"]}
              option={
                data.trend.current.length > 0 ? buildResourceTrendOption(data.trend) : undefined
              }
              height={300}
            />
            <section className={styles.kpi}>
              <div
                className={styles.label}
                style={{ fontWeight: 600, fontSize: 15, color: "var(--gray-900)" }}
              >
                {zh["dash.syncTitle"]}
              </div>
              <div className={styles.syncRow}>
                <span>{zh["dash.lastAggregate"]}</span>
                <span className={styles.time}>
                  {formatDateTime(data.syncStatus.lastAggregateTime, zh["dash.never"] ?? "")}
                </span>
              </div>
              {data.syncStatus.accounts.map((a) => (
                <div
                  className={styles.syncRow}
                  key={`${a.vendor}/${a.accountName}`}
                  data-testid={`sync-row-${a.vendor}-${a.accountName}`}
                >
                  <span>
                    <span className={styles.syncState}>
                      <span
                        className={`${styles.dot} ${a.status === "running" ? styles.dotRunning : ""}`}
                        data-testid={`sync-dot-${a.vendor}-${a.accountName}`}
                        style={{ background: dotColor(a.status) }}
                      />
                      {statusLabel(a.status)}
                    </span>
                    <span className={styles.name}>{a.accountName}</span>
                    <span className={styles.vendor}>{a.vendor}</span>
                  </span>
                  <span className={styles.time}>
                    {formatDateTime(a.lastSyncTime, zh["dash.never"] ?? "")}
                  </span>
                </div>
              ))}
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}

/** 圆点色取 design.md 语义色 Token；未知与 null（无同步记录）一律中性灰，不得借用成功绿。 */
function dotColor(status: string | null): string {
  if (status === "success") return "var(--success-500)";
  if (status === "running") return "var(--warning-500)";
  if (status === "failed") return "var(--danger-500)";
  return "var(--gray-400)";
}

function statusLabel(status: string | null): string {
  if (status === "success") return zh["dash.syncOk"] ?? "";
  if (status === "running") return zh["dash.syncRunning"] ?? "";
  if (status === "failed") return zh["dash.syncFail"] ?? "";
  return zh["dash.syncNone"] ?? "";
}

function Kpi({ label, value, sub }: { label: string; value: string | number; sub: ReactNode }) {
  return (
    <div className={styles.kpi}>
      <div className={styles.bar} />
      <div className={styles.label}>{label}</div>
      <div className={styles.value}>{value}</div>
      <div className={styles.sub}>{sub}</div>
    </div>
  );
}
