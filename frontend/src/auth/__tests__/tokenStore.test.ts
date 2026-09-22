import { beforeEach, describe, expect, it } from "vitest";
import {
  clear,
  getAccess,
  readSession,
  setAccess,
  setRefresh,
  getRefresh,
  writeSession,
} from "../tokenStore";
import { ROLE_ADMIN, ROLE_OPS } from "../roles";

beforeEach(() => {
  clear();
  localStorage.clear();
});

describe("tokenStore", () => {
  it("access 读写只在内存", () => {
    setAccess("A-1");
    expect(getAccess()).toBe("A-1");
    expect(localStorage.getItem("syntime.access")).toBeNull();
  });
  it("refresh 落 localStorage", () => {
    setRefresh("R-1");
    expect(getRefresh()).toBe("R-1");
  });
  it("writeSession/readSession 往返成功", () => {
    writeSession({ username: "ann", role: ROLE_ADMIN });
    expect(readSession()).toEqual({ username: "ann", role: ROLE_ADMIN });
  });
  it("损坏 JSON 与非法 role 一律按未登录", () => {
    localStorage.setItem("syntime.session", "{bad");
    expect(readSession()).toBeNull();
    localStorage.setItem("syntime.session", JSON.stringify({ username: "a", role: "黑客" }));
    expect(readSession()).toBeNull();
  });
  it("clear 清空三处", () => {
    setAccess("A");
    setRefresh("R");
    writeSession({ username: "u", role: ROLE_OPS });
    clear();
    expect(getAccess()).toBeNull();
    expect(getRefresh()).toBeNull();
    expect(readSession()).toBeNull();
  });
});
