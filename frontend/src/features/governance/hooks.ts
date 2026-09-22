import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";
import { API } from "@/api/endpoints";
import type { DetailData, SummaryData, TrendData } from "@/api/types";

export interface GovernanceFilters {
  startDate: string;
  endDate: string;
  keyword?: string;
  projectTag?: string;
  resourceType?: string;
  sortField?: string;
  sortOrder?: "asc" | "desc";
  page?: number;
}

export const governanceKey = {
  all: ["cost"] as const,
  summary: (filters: GovernanceFilters) => ["cost", "summary", filters] as const,
  trend: (filters: GovernanceFilters) => ["cost", "trend", filters] as const,
  details: (
    projectTag: string,
    tagStatus: string | null,
    range: { startDate: string; endDate: string },
    page: number,
  ) => ["cost", "details", projectTag, tagStatus, range, page] as const,
};

const ready = (f: GovernanceFilters) => Boolean(f.startDate && f.endDate);

export function useSummary(filters: GovernanceFilters) {
  return useQuery({
    queryKey: governanceKey.summary(filters),
    queryFn: () => get<SummaryData>(API.costSummary, { ...filters }),
    enabled: ready(filters),
    placeholderData: keepPreviousData,
  });
}

export function useTrend(filters: GovernanceFilters) {
  return useQuery({
    queryKey: governanceKey.trend(filters),
    queryFn: () =>
      get<TrendData>(API.costTrend, {
        startDate: filters.startDate,
        endDate: filters.endDate,
        keyword: filters.keyword,
        projectTag: filters.projectTag,
        resourceType: filters.resourceType,
      }),
    enabled: ready(filters),
    placeholderData: keepPreviousData,
  });
}

export function useDetails(
  projectTag: string,
  tagStatus: string | null,
  range: { startDate: string; endDate: string },
  page: number,
) {
  return useQuery({
    queryKey: governanceKey.details(projectTag, tagStatus, range, page),
    queryFn: () =>
      get<DetailData>(API.costDetail, {
        projectTag,
        tagStatus: tagStatus ?? undefined,
        ...range,
        page,
        pageSize: 20,
        sortField: "amount",
        sortOrder: "desc",
      }),
    enabled: Boolean(projectTag && range.startDate),
    placeholderData: keepPreviousData,
  });
}
