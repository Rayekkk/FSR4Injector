// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

import { callable, definePlugin, toaster } from "@decky/api";
import { ButtonItem, Field, PanelSection, PanelSectionRow, Spinner, staticClasses, ToggleField } from "@decky/ui";
import { FC, useCallback, useEffect, useState } from "react";

declare const SteamClient: any;
declare const appStore: any;

// Steam store categories that mean online play: MMO, Cross-Platform Multiplayer, Online PvP, Online Co-op.
// The generic Multi-player (1) and PvP (49) also cover local-only games, so they do not count.
const ONLINE_CATEGORIES = new Set([20, 27, 36, 38]);

const onlineStatus = (appid: number): "online" | "offline" | "unknown" => {
  try {
    const categories = appStore?.GetAppOverviewByAppID(appid)?.store_category;
    if (!Array.isArray(categories) || !categories.length) return "unknown";
    return categories.some((c: number) => ONLINE_CATEGORIES.has(c)) ? "online" : "offline";
  } catch {
    return "unknown";
  }
};

interface Game {
  appid: number;
  name: string;
  target_dir: string;
  anticheat: boolean;
  enabled: boolean;
  verdict: "ok" | "changed" | "unused" | "failed" | "unknown";
  reason: string;
}

interface Gpu {
  device: number;
  family: number;
  rev: number;
  arch: string;
  model: string | null;
  model_name: string;
  verified: boolean;
}

interface State {
  dll_ready: boolean;
  shim_ready: boolean;
  gpu: Gpu | null;
  recipe: { driver: string; fsr: string; dll_size: number };
  eula_url: string;
  download: { state: "idle" | "running" | "done" | "error"; done: number; total: number; error: string };
  scanned: boolean;
  games: Game[];
}

type ToggleResult = { ok: boolean; error?: string; launch_options?: string; kept?: string[] };

const getState = callable<[], State>("get_state");
const scanGames = callable<[], State>("scan_games");
const downloadDll = callable<[], State>("download_dll");
const cancelDownload = callable<[], State>("cancel_download");
const enableGame = callable<[number, string], ToggleResult>("enable_game");
const disableGame = callable<[number, string], ToggleResult>("disable_game");
const sessionStarted = callable<[number], { managed: boolean }>("session_started");
const sessionEnded = callable<[number, string], { managed: boolean; verdict?: string; reason?: string }>("session_ended");
const startupNotice = callable<[], { message: string }>("startup_notice");

const notify = (title: string, body: string) => toaster.toast({ title, body, duration: 6000 });

// Current launch options straight from Steam. Rejects instead of guessing, so the user's own options are never lost.
const readLaunchOptions = (appid: number) =>
  new Promise<string>((resolve, reject) => {
    let done = false;
    const timer = setTimeout(() => {
      if (!done) { done = true; reg?.unregister?.(); reject(new Error("Steam did not return the launch options")); }
    }, 3000);
    const reg = SteamClient.Apps.RegisterForAppDetails(appid, (details: any) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      setTimeout(() => reg?.unregister?.(), 0);
      resolve(details?.strLaunchOptions ?? "");
    });
  });

const VERDICT_LABEL: Record<Game["verdict"], string> = {
  ok: "✓ FSR4 active",
  changed: "↻ Re-check needed",
  unused: "FSR not used last session",
  failed: "⚠ FSR4 not active",
  unknown: "Not verified yet",
};

const MiB = (b: number) => `${(b / 2 ** 20).toFixed(0)} MiB`;

// The QAM remounts the panel on every open; keep the last state so it renders at once and refreshes underneath.
let lastState: State | null = null;

const Content: FC = () => {
  const [state, setStateRaw] = useState<State | null>(lastState);
  const [busy, setBusy] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState("");
  const [bulk, setBulk] = useState<{ on: boolean; text: string } | null>(null);
  const [error, setError] = useState("");

  const setState = useCallback((s: State) => { lastState = s; setStateRaw(s); }, []);

  const refresh = useCallback(async () => {
    try {
      setState(await getState());
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }, [setState]);

  const rescan = useCallback(async (manual: boolean) => {
    setScanning(true);
    if (manual) setScanResult("");
    try {
      const next = await scanGames();
      setState(next);
      if (manual) setScanResult(`Found ${next.games.length} compatible game${next.games.length === 1 ? "" : "s"}.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setScanning(false);
    }
  }, [setState]);

  // getState is instant; the backend scans the library at startup, so only wait for a scan if it has not finished.
  useEffect(() => {
    getState().then(s => {
      setState(s);
      if (!s.scanned) rescan(false);
    }, e => setError(String(e)));
  }, [setState, rescan]);

  // Poll while the AMD download runs; the RPC itself only returns when it is finished.
  useEffect(() => {
    if (state?.download.state !== "running") return;
    const t = setInterval(() => refresh(), 500);
    return () => clearInterval(t);
  }, [state?.download.state, refresh]);

  const startDownload = async () => {
    if (state) setState({ ...state, download: { ...state.download, state: "running", done: 0 } });
    const next = await downloadDll();
    setState(next);
    if (next.download.state === "error") notify("FSR4 download failed", next.download.error);
  };

  // Returns whether the game ended up in the requested state; errors are shown per game.
  const apply = async (game: Game, on: boolean) => {
    try {
      const current = await readLaunchOptions(game.appid);
      const res = await (on ? enableGame : disableGame)(game.appid, current);
      if (!res.ok) {
        notify(game.name, res.error ?? "Failed");
        return false;
      }
      if (res.launch_options !== undefined && res.launch_options !== current)
        SteamClient.Apps.SetAppLaunchOptions(game.appid, res.launch_options);
      if (res.kept?.length) notify(game.name, `Left files you changed in place: ${res.kept.join(", ")}`);
      return true;
    } catch (e) {
      notify(game.name, String(e));
      return false;
    }
  };

  const toggle = async (game: Game, on: boolean) => {
    setBusy(game.appid);
    await apply(game, on);
    setBusy(null);
    refresh();
  };

  // One game at a time, so each keeps its own launch options and errors. Restoring all is also the cleanup before a
  // real uninstall: plugin updates keep games configured (Decky runs uninstall on update).
  const applyAll = async (on: boolean) => {
    // Turning on skips online games too; a game Steam has no categories for counts as online rather than a guess.
    const candidates = (state?.games ?? []).filter(g => (on ? !g.enabled && !g.anticheat : g.enabled));
    const targets = on ? candidates.filter(g => onlineStatus(g.appid) === "offline") : candidates;
    const skipped = candidates.length - targets.length;
    let ok = 0;
    setBusy(-1);
    for (const [i, g] of targets.entries()) {
      setBulk({ on, text: `${i + 1}/${targets.length}` });
      if (await apply(g, on)) ok++;
    }
    setBulk(null);
    setBusy(null);
    const failed = targets.length - ok;
    const games = (n: number) => `${n} game${n === 1 ? "" : "s"}`;
    notify("FSR4 Injector", (on ? `FSR4 turned on in ${games(ok)}.` : `${games(ok)} restored to how they were.`) +
      (failed ? ` ${games(failed)} could not be changed; see the messages above.` : "") +
      (skipped ? ` Skipped as possibly online: ${games(skipped)}; turn ${skipped === 1 ? "it" : "them"} on by hand if you want.` : ""));
    refresh();
  };

  if (!state) return <PanelSection>{error ? <Field label="Backend unavailable">{error}</Field> : <Spinner />}</PanelSection>;

  const dl = state.download;
  const gpu = state.gpu;
  const canEnable = state.dll_ready && state.shim_ready && !!gpu?.model;
  const pci = gpu ? `1002:${gpu.device.toString(16).padStart(4, "0")}` : "";
  return (
    <>
      <PanelSection title={`AMD FSR ${state.recipe.fsr}`}>
        <PanelSectionRow>
          {!gpu ? (
            <Field label="No AMD GPU found" description="FSR4 Injector needs an AMD Radeon GPU." />
          ) : gpu.model ? (
            <Field label={`${gpu.arch} GPU`}
              description={`PCI ${pci}. AMD's FSR ${state.recipe.fsr} picks its ${gpu.model_name} model here.` +
                (gpu.verified ? "" : " Beta: not tested on this GPU yet; please report how it goes.")} />
          ) : (
            <Field label="GPU not supported"
              description={`AMD's FSR 4 has no model for this GPU (${gpu.arch}, PCI ${pci}), so games stay on FSR 3.`} />
          )}
        </PanelSectionRow>
        {state.dll_ready ? (
          <PanelSectionRow><Field label="AMD FSR4 DLL" description={state.recipe.driver}>Ready</Field></PanelSectionRow>
        ) : dl.state === "running" ? (
          <>
            <PanelSectionRow>
              <Field label="Downloading from AMD">{MiB(dl.done)} / {MiB(dl.total)}</Field>
            </PanelSectionRow>
            <PanelSectionRow><ButtonItem layout="below" onClick={() => cancelDownload().then(setState)}>Cancel</ButtonItem></PanelSectionRow>
          </>
        ) : (
          <>
            <PanelSectionRow>
              <Field
                label="AMD FSR4 DLL needed"
                description={`Fetches the FSR4 library from AMD's official ${state.recipe.driver} package (about 43 MB, nothing else is kept). By downloading you accept the AMD Software EULA: ${state.eula_url}`}
              />
            </PanelSectionRow>
            {dl.state === "error" && <PanelSectionRow><Field label="Last attempt failed">{dl.error}</Field></PanelSectionRow>}
            <PanelSectionRow><ButtonItem layout="below" onClick={startDownload}>Accept and download</ButtonItem></PanelSectionRow>
          </>
        )}
        {!state.shim_ready && <PanelSectionRow><Field label="Plugin files incomplete">bin/amdxc64.dll is missing; reinstall the plugin.</Field></PanelSectionRow>}
      </PanelSection>

      <PanelSection title="Games with FSR 3.1+">
        {state.games.length === 0 && (
          <PanelSectionRow>
            <Field label={!state.scanned || scanning ? "Scanning your library…" : "No compatible games found"} />
          </PanelSectionRow>
        )}
        {state.games.map(g => (
          <PanelSectionRow key={g.appid}>
            <ToggleField
              label={g.name}
              description={g.anticheat ? "Anti-cheat detected: not supported"
                : g.enabled ? `${VERDICT_LABEL[g.verdict]}. ${g.reason}`
                : onlineStatus(g.appid) === "online" ? "Online multiplayer: skipped by Turn on all. Turning it on is at your own risk."
                : undefined}
              checked={g.enabled}
              disabled={busy !== null || (!g.enabled && (g.anticheat || !canEnable))}
              onChange={on => toggle(g, on)}
            />
          </PanelSectionRow>
        ))}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy !== null || scanning} onClick={() => rescan(true)}
            description={scanning ? undefined : scanResult || undefined}>
            {scanning ? "Scanning…" : "Rescan library"}
          </ButtonItem>
        </PanelSectionRow>
        {canEnable && state.games.some(g => !g.enabled && !g.anticheat) && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy !== null} onClick={() => applyAll(true)}
              description="Sets up every compatible game in the list. Online games and games with anti-cheat are skipped.">
              {bulk?.on ? `Turning on… ${bulk.text}` : "Turn on FSR4 in all games"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {state.games.some(g => g.enabled) && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy !== null} onClick={() => applyAll(false)}
              description="Removes the plugin's files and launch option from every game, leaving them as they were. Do this before uninstalling.">
              {bulk && !bulk.on ? `Restoring… ${bulk.text}` : "Turn off FSR4 and restore all games"}
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
};

// A "4" badge for FSR 4.
const Fsr4Icon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" style={{ width: "1em", height: "1em" }}>
    <rect x="2.5" y="2.5" width="19" height="19" rx="4.5" />
    <path d="M14.5 6.5 8 14.5h9" />
    <path d="M14.5 6.5v11" />
  </svg>
);

export default definePlugin(() => {
  // After a SteamOS update, say once that games are re-checked on their next session.
  startupNotice().then(r => { if (r.message) notify("FSR4 Injector", r.message); }, () => {});

  // Never fail silently: when a game we manage exits, tell the user if FSR4 was requested but not active.
  // Launch options are passed on exit so a session our DLL missed can name the cause (e.g. another tool rewrote them).
  const lifetime = SteamClient.GameSessions.RegisterForAppLifetimeNotifications(async (n: any) => {
    try {
      if (n?.bRunning) {
        await sessionStarted(n.unAppID);
        return;
      }
      const options = await readLaunchOptions(n.unAppID).catch(() => "");
      const res = await sessionEnded(n.unAppID, options);
      if (res.managed && res.verdict === "failed") notify("FSR4 not active", res.reason ?? "");
    } catch {
      // backend restarting; the panel shows the same verdict next time it opens
    }
  });

  return {
    name: "FSR4 Injector",
    titleView: <div className={staticClasses.Title}>FSR4 Injector</div>,
    content: <Content />,
    icon: <Fsr4Icon />,
    onDismount() {
      lifetime?.unregister?.();
    },
  };
});
