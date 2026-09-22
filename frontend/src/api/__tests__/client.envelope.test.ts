import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BizError, api, call, resetClientState, setToastHandler } from "../client";

let mock: MockAdapter;
const toast = vi.fn();

beforeEach(() => {
  mock = new MockAdapter(api);
  toast.mockClear();
  setToastHandler(toast);
});
afterEach(() => {
  mock.restore();
  resetClientState();
});

describe("信封解包", () => {
  it("code=0 时返回 data 本体", async () => {
    mock.onGet("/dashboard/").reply(200, { code: 0, message: "ok", data: { cards: { x: 1 } } });
    await expect(
      call<{ cards: { x: number } }>({ method: "get", url: "/dashboard/" }),
    ).resolves.toEqual({ cards: { x: 1 } });
  });

  it("data 为 null 的合法成功（logout）原样返回 null", async () => {
    mock.onPost("/auth/logout/").reply(200, { code: 0, message: "ok", data: null });
    await expect(
      call({ method: "post", url: "/auth/logout/", data: { refresh: "R" } }),
    ).resolves.toBeNull();
  });

  it("非信封响应透传（防御文件下载等）", async () => {
    mock.onGet("/files/x.csv").reply(200, "raw-csv");
    await expect(call({ method: "get", url: "/files/x.csv" })).resolves.toBe("raw-csv");
  });
});

describe("错误码分流（读 code 不读 HTTP 状态）", () => {
  it("40300 以 HTTP 200 返回：仍 reject BizError{code:40300,httpStatus:200} 并 toast", async () => {
    mock.onGet("/assets/").reply(200, { code: 40300, message: "无权限访问该资源", data: null });
    const err = (await call({ method: "get", url: "/assets/" }).catch(
      (e: unknown) => e as BizError,
    )) as BizError;
    expect(err).toBeInstanceOf(BizError);
    expect(err.code).toBe(40300);
    expect(err.httpStatus).toBe(200);
    expect(toast).toHaveBeenCalledWith("无权限访问该资源");
  });

  it("40001（HTTP 400）toast 并 reject", async () => {
    mock.onPost("/token/").reply(400, { code: 40001, message: "用户名或密码错误", data: null });
    const err = (await call({ method: "post", url: "/token/" }).catch(
      (e: unknown) => e as BizError,
    )) as BizError;
    expect(err.code).toBe(40001);
    expect(toast).toHaveBeenCalledWith("用户名或密码错误");
  });

  it.each([
    [42900, 429, 50, "操作过于频繁"],
    [50000, 500, 0, "系统内部错误"],
    [40900, 200, 0, "状态冲突"],
  ])("code %i 走 toast", async (code, http, _unused, message) => {
    mock.onGet("/conflict/").reply(http, { code, message, data: null });
    await expect(call({ method: "get", url: "/conflict/" })).rejects.toMatchObject({ code });
    expect(toast).toHaveBeenCalledWith(message);
  });

  it("网络异常归一为 code=-1 并 toast 中文提示", async () => {
    mock.onGet("/ping/").networkError();
    const err = (await call({ method: "get", url: "/ping/" }).catch(
      (e: unknown) => e as BizError,
    )) as BizError;
    expect(err).toBeInstanceOf(BizError);
    expect(err.code).toBe(-1);
    expect(toast).toHaveBeenCalledWith("网络异常，请稍后重试");
  });

  it("超时归一为 code=-1 并 toast 中文提示", async () => {
    mock.onGet("/slow/").timeout();
    const err = (await call({ method: "get", url: "/slow/" }).catch(
      (e: unknown) => e as BizError,
    )) as BizError;
    expect(err).toBeInstanceOf(BizError);
    expect(err.code).toBe(-1);
    expect(err.message).toBe("请求超时，请稍后重试");
    expect(toast).toHaveBeenCalledWith("请求超时，请稍后重试");
  });

  it("GET params 序列化进 URL", async () => {
    let seen = "";
    mock.onGet(/\/assets\//).reply((cfg) => {
      seen = cfg.url ?? "";
      return [200, { code: 0, message: "ok", data: { list: [] } }];
    });
    await call({ method: "get", url: "/assets/", params: { page: 2, pageSize: 50 } });
    expect(seen).toContain("page=2");
    expect(seen).toContain("pageSize=50");
  });

  it("baseURL 为 /api", () => {
    expect(api.defaults.baseURL).toBe("/api");
  });
});
