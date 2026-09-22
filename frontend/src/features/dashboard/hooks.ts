import { useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";
import { API } from "@/api/endpoints";
import type { DashboardData } from "@/api/types";

export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: () => get<DashboardData>(API.dashboard),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
