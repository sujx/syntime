import { describe, expect, it } from "vitest";
import { ALL_ROLES, ROLE_FINANCE, ROLE_ADMIN, ROLE_OPS } from "@/auth/roles";
import { NAV_GROUPS, DEFAULT_PATH, canAccess, findItem, visibleNav } from "../menu";

const flat = (role: (typeof ALL_ROLES)[number] | null) =>
  visibleNav(role).flatMap((g) => g.items.map((i) => i.key));

describe("visibleNav", () => {
  it("三个分组标题齐全（管理员视角）", () => {
    expect(visibleNav(ROLE_ADMIN).map((g) => g.titleKey)).toEqual([
      "nav.groupCost",
      "nav.groupResource",
      "nav.groupSystem",
    ]);
  });
  it("管理员与云运维可见项一致（8 项）", () => {
    expect(flat(ROLE_ADMIN)).toEqual(flat(ROLE_OPS));
    expect(flat(ROLE_ADMIN)).toHaveLength(8);
  });
  it("财务人员 6 项：无资产清单与成本治理", () => {
    const keys = flat(ROLE_FINANCE);
    expect(keys).toHaveLength(6);
    expect(keys).not.toContain("asset");
    expect(keys).not.toContain("governance");
  });
  it("未登录/未知角色为空", () => {
    expect(visibleNav(null)).toEqual([]);
  });
  it("剔除空分组：财务人员系统设置组仍在（alertConfig 对全体可见）", () => {
    for (const g of visibleNav(ROLE_FINANCE)) expect(g.items.length).toBeGreaterThan(0);
  });
  it("事件中心对全体可见且带未读徽标声明", () => {
    const ev = findItem("/event");
    expect(ev?.roles).toBeNull();
    expect(ev?.badge).toBe("eventUnread");
  });
  it("二期占位集合", () => {
    const phase2 = NAV_GROUPS.flatMap((g) => g.items)
      .filter((i) => i.phase2)
      .map((i) => i.key);
    expect(new Set(phase2)).toEqual(new Set(["budget", "cloudAccount", "alertConfig"]));
  });
});

describe("canAccess / DEFAULT_PATH", () => {
  it("财务访问 /asset 为 false", () => expect(canAccess(ROLE_FINANCE, "/asset")).toBe(false));
  it("财务访问 /dashboard 为 true", () => expect(canAccess(ROLE_FINANCE, "/dashboard")).toBe(true));
  it("未知路径为 false", () => expect(canAccess(ROLE_ADMIN, "/nope")).toBe(false));
  it("默认落地页对全角色可达", () => expect(canAccess(ROLE_FINANCE, DEFAULT_PATH)).toBe(true));
  it("第一项即默认页", () => expect(visibleNav(ROLE_ADMIN)[0]?.items[0]?.path).toBe(DEFAULT_PATH));
});
