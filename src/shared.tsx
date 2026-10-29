// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// Small helpers of the panel: labels, online games, Decky Launch Options and the clipboard.
import { Game, State } from "./api";

// Steam store categories that mean online play: MMO, Cross-Platform Multiplayer, Online PvP, Online Co-op.
// The generic Multi-player (1) and PvP (49) also cover local-only games, so they do not count.
const ONLINE_CATEGORIES = new Set([20, 27, 36, 38]);

export const onlineStatus = (appid: number): "online" | "offline" | "unknown" => {
  try {
    const categories = appStore?.GetAppOverviewByAppID(appid)?.store_category;
    if (!Array.isArray(categories) || !categories.length) return "unknown";
    return categories.some(c => ONLINE_CATEGORIES.has(c)) ? "online" : "offline";
  } catch {
    return "unknown";
  }
};

export const VERDICT_LABEL: Record<Game["verdict"], string> = {
  ok: "✓ FSR4 active",
  changed: "↻ Re-check needed",
  unused: "FSR not used last session",
  failed: "⚠ FSR4 not active",
  unknown: "Not verified yet",
};

export const MB = (b: number) => `${(b / 2 ** 20).toFixed(0)} MB`;

export const ANTICHEAT_WARNING = "Anti-cheat detected: adding DLLs to this game can get you kicked or banned in online play. " +
  "Turning FSR4 on is at your own risk.";

// Decky Launch Options (github.com/Rayekkk/DeckyLaunchOptions) imports launch options other plugins offer; it asks the
// user to confirm. Stable ids make a second import update these entries instead of adding new ones.
export const hasLaunchOptionsPlugin = () =>
  typeof window !== "undefined" && !!(window as Window & { hasDeckyLaunchOptions?: boolean }).hasDeckyLaunchOptions;
export const offerToLaunchOptionsPlugin = (copy: State["copy_options"]) => {
  const [token, watermark] = copy.watermark.replace(" %command%", "").split(" ");
  window.dispatchEvent(new CustomEvent("dlo-add-launch-options", {
    detail: [
      { id: "fsr4-injector", group: "FSR4 Injector", name: "FSR4 Injector", on: token, off: "", enableGlobally: false },
      { id: "fsr4-injector-watermark", group: "FSR4 Injector", name: "AMD FSR4 watermark", on: watermark, off: "",
        enableGlobally: false },
    ],
  }));
};

// The Steam client does not always grant the async clipboard API to plugins; fall back to a selected textarea.
export const copyText = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
};
