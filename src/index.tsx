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
  managed_options?: boolean; // the plugin set this game's launch options
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
  version: string;
  dll_ready: boolean;
  shim_ready: boolean;
  gpu: Gpu | null;
  recipe: { driver: string; fsr: string; dll_size: number };
  eula_url: string;
  download: { state: "idle" | "running" | "done" | "error"; done: number; total: number; error: string };
  settings: { auto_launch_options: boolean; watermark: boolean };
  copy_options: { plain: string; watermark: string };
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
const setSetting = callable<[string, boolean], State>("set_setting");
const verifyLibrary = callable<[], State>("verify_library");
const applyWatermark = callable<[number, string], { ok: boolean; launch_options: string }>("apply_watermark");

interface UpdateInfo { current_version?: string; latest_version?: string; update_available?: boolean; asset_name?: string; error?: string }
const checkForUpdates = callable<[], UpdateInfo>("check_for_updates");
const performUpdate = callable<[string], { path?: string; version?: string; error?: string }>("perform_update");

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

const ANTICHEAT_WARNING = "Anti-cheat detected: adding DLLs to this game can get you kicked or banned in online play. " +
  "Turning FSR4 on is at your own risk.";

// Decky Launch Options (github.com/Rayekkk/DeckyLaunchOptions) imports launch options other plugins offer; it asks the
// user to confirm. Stable ids make a second import update these entries instead of adding new ones.
const hasLaunchOptionsPlugin = () => typeof window !== "undefined" && !!(window as any).hasDeckyLaunchOptions;
const offerToLaunchOptionsPlugin = (copy: State["copy_options"]) => {
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
const copyText = async (text: string) => {
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

// The QAM remounts the panel on every open; keep the last state so it renders at once and refreshes underneath.
let lastState: State | null = null;

const Content: FC = () => {
  const [state, setStateRaw] = useState<State | null>(lastState);
  const [busy, setBusy] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState("");
  const [bulk, setBulk] = useState<{ kind: "on" | "off" | "repair"; text: string } | null>(null);
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
      setBulk({ kind: on ? "on" : "off", text: `${i + 1}/${targets.length}` });
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

  // Repair: AMD's library must still pass its checksum, then every game that has FSR4 on is set up again.
  const repairAll = async () => {
    setBusy(-1);
    try {
      const next = await verifyLibrary();
      setState(next);
      if (!next.dll_ready) {
        notify("FSR4 Injector", "AMD's FSR4 library is missing or damaged. Download it again above, then repair.");
        return;
      }
      const targets = next.games.filter(g => g.enabled);
      let ok = 0;
      for (const [i, g] of targets.entries()) {
        setBulk({ kind: "repair", text: `${i + 1}/${targets.length}` });
        if (await apply(g, true)) ok++;
      }
      notify("FSR4 Injector", `Repaired ${ok} of ${targets.length} game${targets.length === 1 ? "" : "s"}.`);
    } catch (e) {
      notify("FSR4 Injector", String(e));
    } finally {
      setBulk(null);
      setBusy(null);
      refresh();
    }
  };

  // The new setting applies at once to every game whose launch options the plugin manages.
  const setWatermark = async (on: boolean) => {
    setBusy(-1);
    try {
      const next = await setSetting("watermark", on);
      setState(next);
      for (const g of next.games.filter(g => g.enabled && g.managed_options)) {
        const current = await readLaunchOptions(g.appid);
        const res = await applyWatermark(g.appid, current);
        if (res.ok && res.launch_options !== current) SteamClient.Apps.SetAppLaunchOptions(g.appid, res.launch_options);
      }
    } catch (e) {
      notify("FSR4 Injector", String(e));
    }
    setBusy(null);
    refresh();
  };

  const copy = async (text: string) =>
    notify("FSR4 Injector", (await copyText(text)) ? `Copied: ${text}` : "Copying is not available here.");

  if (!state) return <PanelSection>{error ? <Field label="Backend unavailable">{error}</Field> : <Spinner />}</PanelSection>;

  const settings = state.settings ?? { auto_launch_options: true, watermark: false };
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
              description={<>
                {g.enabled ? `${VERDICT_LABEL[g.verdict]}. ${g.reason}`
                  : !g.anticheat && onlineStatus(g.appid) === "online"
                    ? "Online multiplayer: skipped by Turn on all. Turning it on is at your own risk." : null}
                {g.anticheat && <div style={{ color: "#ff5c5c" }}>{ANTICHEAT_WARNING}</div>}
              </>}
              checked={g.enabled}
              disabled={busy !== null || (!g.enabled && !canEnable)}
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
              {bulk?.kind === "on" ? `Turning on… ${bulk.text}` : "Turn on FSR4 in all games"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {state.games.some(g => g.enabled) && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy !== null} onClick={() => applyAll(false)}
              description="Removes the plugin's files and launch option from every game, leaving them as they were. Do this before uninstalling.">
              {bulk?.kind === "off" ? `Restoring… ${bulk.text}` : "Turn off FSR4 and restore all games"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {state.games.some(g => g.enabled) && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy !== null} onClick={repairAll}
              description="Checks AMD's library and puts the plugin's files and launch option back in every game that has FSR4 on, for example after a game update or Steam's file check.">
              {bulk?.kind === "repair" ? `Repairing… ${bulk.text}` : "Repair FSR4 in all games"}
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Launch options">
        <PanelSectionRow>
          <ToggleField
            label="Add launch option automatically"
            description={`Turning FSR4 on for a game adds ${state.copy_options.plain} to its launch options. ` +
              "Off: add it yourself; the plugin then leaves the game's launch options alone."}
            checked={settings.auto_launch_options}
            disabled={busy !== null}
            onChange={on => setSetting("auto_launch_options", on).then(setState, e => notify("FSR4 Injector", String(e)))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Show AMD's FSR4 watermark"
            description="Also adds FSR_WATERMARK=1, so AMD's library shows which FSR 4 model runs. Applies to the games set up above at once."
            checked={settings.auto_launch_options && settings.watermark}
            disabled={busy !== null || !settings.auto_launch_options}
            onChange={setWatermark}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => copy(state.copy_options.plain)}
            description={state.copy_options.plain}>
            Copy launch options
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => copy(state.copy_options.watermark)}
            description={state.copy_options.watermark}>
            Copy launch options + watermark
          </ButtonItem>
        </PanelSectionRow>
        {hasLaunchOptionsPlugin() && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => offerToLaunchOptionsPlugin(state.copy_options)}
              description={"Adds FSR4 Injector and AMD FSR4 watermark to Decky Launch Options, to switch per game there. " +
                "Then turn off Add launch option automatically above; FSR4 still has to be on here for the game's files. " +
                "To combine with other WINEDLLOVERRIDES options, add an env variable merge for it with ; in Decky Launch Options."}>
              Add to Decky Launch Options
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="About">
        <PanelSectionRow>
          <Field label={`FSR4 Injector · v${state.version}`}
            description="AMD's official FSR 4 upscaler, with the Lite model made for handhelds, in FSR 3.1 games under Proton." />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Author" description="Rayek · BSD-3-Clause open-source plugin; the amdxc64 shim is LGPL-2.1." />
        </PanelSectionRow>
      </PanelSection>
      <Updates version={state.version} />
    </>
  );
};

// Survives the QAM remounting the panel, like the panel state.
let updateView: { info: UpdateInfo | null; checking: boolean; downloading: boolean; path: string | null } =
  { info: null, checking: false, downloading: false, path: null };

const versionTag = (value: string) => (
  <span style={{ fontWeight: 700, color: "var(--gpColor-White, #fff)", background: "rgba(102,192,244,.18)", borderRadius: "4px", padding: "1px 6px" }}>
    v{value}
  </span>
);

// Same flow as the Companion plugins: check GitHub, download the verified release ZIP to Downloads, install it by hand.
const Updates: FC<{ version: string }> = ({ version }) => {
  const [view, setViewRaw] = useState(updateView);
  const setView = (next: Partial<typeof updateView>) => { updateView = { ...updateView, ...next }; setViewRaw(updateView); };
  const { info, checking, downloading, path } = view;

  const check = async () => {
    if (updateView.checking || updateView.downloading) return;
    setView({ checking: true, info: null, path: null });
    try {
      setView({ info: await checkForUpdates() });
    } catch (e) {
      setView({ info: { error: String(e) } });
    }
    setView({ checking: false });
  };

  const download = async () => {
    const expected = updateView.info?.latest_version;
    if (!expected || updateView.checking || updateView.downloading) return;
    setView({ downloading: true });
    try {
      const res = await performUpdate(expected);
      if (res.path && res.version === expected) setView({ path: res.path });
      else setView({ info: { ...(updateView.info ?? {}), error: res.error ?? "The download did not finish." } });
    } catch (e) {
      setView({ info: { ...(updateView.info ?? {}), error: String(e) } });
    }
    setView({ downloading: false });
  };

  return (
    <PanelSection title="Updates">
      <PanelSectionRow>
        <div style={{ fontSize: "12px", color: "var(--gpColor-TextMuted, rgba(255,255,255,.6))", overflowWrap: "anywhere" }}>
          Installed: {versionTag(info?.current_version ?? version)}
          {info?.latest_version && !info.error && <>{" · "}Latest: {versionTag(info.latest_version)}</>}
        </div>
      </PanelSectionRow>
      {info?.error && (
        <PanelSectionRow>
          <div style={{ padding: "8px", borderRadius: "4px", background: "rgba(248,113,113,.14)", color: "var(--gpColor-Red, #f87171)", overflowWrap: "anywhere" }}>
            {info.error}
          </div>
        </PanelSectionRow>
      )}
      {info && !info.error && !info.update_available && !path && (
        <PanelSectionRow><div style={{ fontSize: "12px", color: "var(--gpColor-Green, #4ade80)" }}>Up to date</div></PanelSectionRow>
      )}
      {info?.update_available && info.asset_name && !path && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={checking || downloading} onClick={download}
            description="Downloads the release ZIP from GitHub to the Downloads folder and checks it.">
            {downloading ? "Downloading…" : `Download v${info.latest_version}`}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {path && (
        <PanelSectionRow>
          <Field focusable label="Update downloaded" description={<span>
            Saved to <span style={{ fontFamily: "monospace", overflowWrap: "anywhere" }}>{path}</span>. To install:
            Decky → Settings → Developer → Install Plugin from ZIP. Your games stay set up.
          </span>} />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={checking || downloading} onClick={check}
          description="Compares the installed version with the latest GitHub release.">
          {checking ? "Checking…" : "Check for updates"}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
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
