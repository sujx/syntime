import dayjs from "dayjs";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/utils/datetime";
import { localText } from "@/test/localTime";

describe("formatDateTime", () => {
  it("把带偏移的 ISO 串转成本地墙上时间", () => {
    const iso = "2026-09-21T02:30:00+08:00";
    expect(formatDateTime(iso)).toBe(localText(iso));
  });
  it("同一时刻的不同偏移写法渲染一致（证明真的做了换算而非切片）", () => {
    expect(formatDateTime("2026-09-21T02:30:00+08:00")).toBe(
      formatDateTime("2026-09-20T18:30:00Z"),
    );
  });
  it("null / 非法值回落 fallback", () => {
    expect(formatDateTime(null, "尚未同步")).toBe("尚未同步");
    expect(formatDateTime("not-a-date", "尚未同步")).toBe("尚未同步");
    expect(formatDateTime(null)).toBe("--");
  });
});

describe("dayjs 语言包", () => {
  // antd 的 ConfigProvider 传下的是 "zh_CN"（下划线），dayjs 无此语言包名，
  // 会回落到全局 locale；全局不设 zh-cn 时日期面板就出英文月份缩写。
  it("全局 locale 为 zh-cn，日期面板月份为中文", () => {
    expect(dayjs.locale()).toBe("zh-cn");
    expect(dayjs("2026-07-01").format("MMM")).toBe("7月");
  });
});
