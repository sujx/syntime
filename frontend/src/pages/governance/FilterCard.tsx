import { Input, Segmented, Select } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import type { ResourceTypeInfo } from "@/api/types";
import type { GovernanceFilters } from "@/features/governance/hooks";
import { zh } from "@/i18n/zh";
import styles from "./governance.module.css";

type QuickKey = "thisMonth" | "lastMonth" | "last30" | "last90";

// quickRange 与 FilterCard 同处一个模块（见任务简报），非组件导出触发 react-refresh 提示，此处局部豁免
/* eslint-disable-next-line react-refresh/only-export-components */
export function quickRange(key: QuickKey, today: Dayjs = dayjs()): [Dayjs, Dayjs] {
  if (key === "lastMonth") {
    const m = today.subtract(1, "month");
    return [m.startOf("month"), m.endOf("month")];
  }
  if (key === "last30") return [today.subtract(29, "day"), today];
  if (key === "last90") return [today.subtract(89, "day"), today];
  return [today.startOf("month"), today];
}

export function FilterCard({
  value,
  resourceTypes,
  onChange,
}: {
  value: GovernanceFilters;
  resourceTypes: ResourceTypeInfo[];
  onChange: (next: GovernanceFilters) => void;
}) {
  const [quick, setQuick] = useState<QuickKey>("thisMonth");
  const [keyword, setKeyword] = useState(value.keyword ?? "");
  const apply = (patch: Partial<GovernanceFilters>) =>
    onChange({ ...value, page: undefined, ...patch } as GovernanceFilters);
  return (
    <div className={`${styles.card} ${styles.filterGrid}`} data-testid="gov-filter">
      <Segmented
        value={quick}
        options={[
          { value: "thisMonth", label: zh["gov.quickThisMonth"] },
          { value: "lastMonth", label: zh["gov.quickLastMonth"] },
          { value: "last30", label: zh["gov.quickLast30"] },
          { value: "last90", label: zh["gov.quickLast90"] },
        ]}
        onChange={(q) => {
          const key = q as QuickKey;
          setQuick(key);
          const [s, e] = quickRange(key);
          apply({ startDate: s.format("YYYY-MM-DD"), endDate: e.format("YYYY-MM-DD") });
        }}
      />
      <Input.Search
        allowClear
        placeholder={zh["gov.filterKeyword"]}
        value={keyword}
        style={{ maxWidth: 220 }}
        onSearch={(v) => apply({ keyword: v || undefined })}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <Select
        style={{ minWidth: 160 }}
        value={value.resourceType ?? "all"}
        onChange={(v) => apply({ resourceType: v === "all" ? undefined : (v as string) })}
        options={[
          { value: "all", label: zh["gov.allTypes"] },
          ...resourceTypes.map((r) => ({ value: r.code, label: r.displayName })),
        ]}
      />
    </div>
  );
}
