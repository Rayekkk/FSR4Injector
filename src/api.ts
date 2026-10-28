// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The backend's methods, typed, and Steam's launch options. Every call goes through settle(): it never rejects, a
// dead backend is { ok: false, error } like any refusal (DeckyKit D2).
import { callable, toaster } from "@decky/api";
import { Result, settle } from "./result";

export interface Game {
  appid: number;
  name: string;
  target_dir: string;
  anticheat: boolean;
  enabled: boolean;
  verdict: "ok" | "changed" | "unused" | "failed" | "unknown";
  reason: string;
  managed_options?: boolean; // the plugin set this game's launch options
}

export interface Gpu {
  device: number;
  family: number;
  rev: number;
  arch: string;
  model: string | null;
  model_name: string;
  verified: boolean;
}

export interface Download { state: "idle" | "running" | "done" | "error"; done: number; total: number; error: string }

export interface State {
  version: string;
  dll_ready: boolean;
  shim_ready: boolean;
  gpu: Gpu | null;
  recipe: { driver: string; fsr: string; dll_size: number };
  eula_url: string;
  download: Download;
  settings: { auto_launch_options: boolean; watermark: boolean };
  copy_options: { plain: string; watermark: string };
  scanned: boolean;
  error: string; // the manifest cannot be trusted: no game can be changed
  games: Game[];
}

export type StateResult = Result<State>;
export type ToggleResult = StateResult & { launch_options?: string; kept?: string[] };
export interface UpdateInfo extends Result<never> {
  current_version?: string; latest_version?: string; update_available?: boolean; download_available?: boolean;
}

const rpc = <A extends unknown[], R extends Result<unknown>>(name: string) => {
  const call = callable<A, R>(name);
  return (...args: A) => settle(call(...args));
};

export const getState = rpc<[], StateResult>("get_state");
export const scanGames = rpc<[], StateResult>("scan_games");
export const downloadDll = rpc<[], StateResult>("download_dll");
export const downloadProgress = rpc<[], Result<never> & { download?: Download; dll_ready?: boolean }>("download_progress");
export const cancelDownload = rpc<[], StateResult>("cancel_download");
export const enableGame = rpc<[number, string], ToggleResult>("enable_game");
export const disableGame = rpc<[number, string], ToggleResult>("disable_game");
export const launchOptionsSaved = rpc<[number, string], StateResult>("launch_options_saved");
export const sessionStarted = rpc<[number], Result<never> & { managed?: boolean }>("session_started");
export const sessionEnded = rpc<[number, string], Result<never> & { managed?: boolean; verdict?: string; reason?: string }>("session_ended");
export const startupNotice = rpc<[], Result<never>>("startup_notice");
export const setSetting = rpc<[string, boolean], StateResult>("set_setting");
export const verifyLibrary = rpc<[], StateResult>("verify_library");
export const applyWatermark = rpc<[number, string], Result<never> & { launch_options?: string }>("apply_watermark");
export const checkForUpdates = rpc<[], UpdateInfo>("check_for_updates");
export const performUpdate = rpc<[string], Result<never> & { path?: string; version?: string }>("perform_update");

export const notify = (title: string, body: string) => toaster.toast({ title, body, duration: 6000 });

export const off = (u: SteamUnregister | undefined) => (typeof u === "function" ? u() : u?.unregister());

// Current launch options straight from Steam. Rejects instead of guessing, so the user's own options are never lost.
export const readLaunchOptions = (appid: number) =>
  new Promise<string>((resolve, reject) => {
    let done = false;
    const timer = setTimeout(() => {
      if (!done) { done = true; off(reg); reject(new Error("Steam did not return the launch options")); }
    }, 3000);
    const reg = SteamClient.Apps.RegisterForAppDetails(appid, details => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      setTimeout(() => off(reg), 0);
      resolve(details?.strLaunchOptions ?? "");
    });
  });

// Writes launch options to Steam, reads back what Steam kept and tells the backend, so turning FSR4 off later
// restores the user's own options exactly (and a write Steam did not keep is reported, not assumed).
export const saveLaunchOptions = async (appid: number, options: string) => {
  SteamClient.Apps.SetAppLaunchOptions(appid, options);
  return launchOptionsSaved(appid, await readLaunchOptions(appid));
};
