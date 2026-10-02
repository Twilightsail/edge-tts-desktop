import { invoke } from "@tauri-apps/api/core";
import { save } from "@tauri-apps/plugin-dialog";
import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";

export const isDesktop = "__TAURI_INTERNALS__" in window;

export const desktopConn = () => invoke<{ baseUrl: string; token: string }>("get_conn");

/** 原生另存为对话框；用户取消返回 null。 */
export const pickSavePath = (defaultName: string, ext: string) =>
  save({ defaultPath: defaultName, filters: [{ name: ext.toUpperCase(), extensions: [ext] }] });

/** 系统通知；仅桌面端、首次使用时请求授权，被拒绝则静默忽略。 */
export async function notifyDesktop(title: string, body: string) {
  if (!isDesktop) return;
  try {
    let granted = await isPermissionGranted();
    if (!granted) granted = (await requestPermission()) === "granted";
    if (granted) sendNotification({ title, body });
  } catch {
    /* 通知失败不影响主流程 */
  }
}
