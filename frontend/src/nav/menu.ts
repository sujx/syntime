import type { Role } from "@/auth/roles";
import { ROLE_ADMIN, ROLE_OPS } from "@/auth/roles";

export interface NavItem {
  key: string;
  labelKey: string;
  path: string;
  /** null = 全角色可见 */
  roles: readonly Role[] | null;
  badge?: "eventUnread";
  phase2?: boolean;
}
export interface NavGroup {
  titleKey: string;
  items: NavItem[];
}

const OPS_AND_ADMIN: readonly Role[] = [ROLE_ADMIN, ROLE_OPS];

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    titleKey: "nav.groupCost",
    items: [
      { key: "dashboard", labelKey: "nav.dashboard", path: "/dashboard", roles: null },
      {
        key: "projectSettlement",
        labelKey: "nav.projectSettlement",
        path: "/finance/project-settlement",
        roles: null,
      },
      { key: "budget", labelKey: "nav.budget", path: "/budget", roles: null, phase2: true },
      { key: "governance", labelKey: "nav.governance", path: "/governance", roles: OPS_AND_ADMIN },
    ],
  },
  {
    titleKey: "nav.groupResource",
    items: [
      { key: "asset", labelKey: "nav.asset", path: "/asset", roles: OPS_AND_ADMIN },
      {
        key: "cloudAccount",
        labelKey: "nav.cloudAccount",
        path: "/cloud-account",
        roles: null,
        phase2: true,
      },
      { key: "event", labelKey: "nav.event", path: "/event", roles: null, badge: "eventUnread" },
    ],
  },
  {
    titleKey: "nav.groupSystem",
    items: [
      {
        key: "alertConfig",
        labelKey: "nav.alertConfig",
        path: "/alert-config",
        roles: null,
        phase2: true,
      },
    ],
  },
];

export const DEFAULT_PATH = "/dashboard";

export function visibleNav(role: Role | null): NavGroup[] {
  if (!role) return [];
  return NAV_GROUPS.map((group) => ({
    titleKey: group.titleKey,
    items: group.items.filter((item) => item.roles === null || item.roles.includes(role)),
  })).filter((group) => group.items.length > 0);
}

export function findItem(path: string): NavItem | undefined {
  return NAV_GROUPS.flatMap((g) => g.items).find((item) => item.path === path);
}

export function canAccess(role: Role | null, path: string): boolean {
  const item = findItem(path);
  if (!item || !role) return false;
  return item.roles === null || item.roles.includes(role);
}
