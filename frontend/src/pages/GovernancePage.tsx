import { useState } from "react";
import type { ResourceTypeInfo, SummaryRow } from "@/api/types";
import type { GovernanceFilters } from "@/features/governance/hooks";
import { zh } from "@/i18n/zh";
import { FilterCard, quickRange } from "./governance/FilterCard";
import { SummaryTable } from "./governance/SummaryTable";

export default function GovernancePage() {
  const [s, e] = quickRange("thisMonth");
  const [filters, setFilters] = useState<GovernanceFilters>({
    startDate: s.format("YYYY-MM-DD"),
    endDate: e.format("YYYY-MM-DD"),
  });
  const [resourceTypes, setResourceTypes] = useState<ResourceTypeInfo[]>([]);
  const [detailRow, setDetailRow] = useState<SummaryRow | null>(null);
  return (
    <div data-testid="page-governance">
      <h1 className="page-title" style={{ marginBottom: "var(--space-5)" }}>
        {zh["nav.governance"]}
      </h1>
      <FilterCard value={filters} resourceTypes={resourceTypes} onChange={setFilters} />
      <SummaryTable
        filters={filters}
        onFiltersChange={setFilters}
        onRowOpen={setDetailRow}
        onTypes={setResourceTypes}
      />
      {detailRow ? <span data-testid="detail-anchor">{detailRow.projectTag}</span> : null}
    </div>
  );
}
