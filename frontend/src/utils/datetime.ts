import dayjs from "dayjs";
import "dayjs/locale/zh-cn";

// antd 的 ConfigProvider 只把 "zh_CN"（下划线）传给 rc-picker，dayjs 没有这个名字的
// 语言包，会回落到全局 locale；全局不设成 zh-cn，日期面板就出英文月份缩写。
dayjs.locale("zh-cn");

/** 后端 ISO（UTC）转本地墙上时间；缺失或非法值回落 fallback。 */
export function formatDateTime(iso: string | null, fallback = "--"): string {
  if (!iso) return fallback;
  const d = dayjs(iso);
  return d.isValid() ? d.format("YYYY-MM-DD HH:mm") : fallback;
}
