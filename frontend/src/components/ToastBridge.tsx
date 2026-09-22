import { App as AntdApp } from "antd";
import { useEffect } from "react";
import { setToastHandler } from "@/api/client";

export function ToastBridge() {
  const { message } = AntdApp.useApp();
  useEffect(() => {
    setToastHandler((m) => message.error(m));
    return () => setToastHandler(null);
  }, [message]);
  return null;
}
