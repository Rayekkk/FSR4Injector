// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The Quick Access panel: AMD's library, the games, launch options and the About page with updates.
import { useQuickAccessVisible } from "@decky/api";
import { Field, Focusable, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { FC, ReactNode, useCallback, useEffect, useState } from "react";
import { AboutPage, INSTALL_HINT, UpdateController, UpdateSection } from "./about";
import {
  applyWatermark, cancelDownload, checkForUpdates, disableGame, downloadDll, downloadProgress, enableGame, Game,
  getState, performUpdate, readLaunchOptions, saveLaunchOptions, scanGames, setSetting, State, StateResult, verifyLibrary,
} from "./api";
import {
  ANTICHEAT_WARNING, copyText, hasLaunchOptionsPlugin, MB, offerToLaunchOptionsPlugin, onlineStatus, VERDICT_LABEL,
} from "./shared";
import { errorText } from "./result";
import { ActionButton, colors, infoRow, notify, PageHeader, SectionLink, statusPlaceholder } from "./ui";

const NAME = "FSR4 Injector";

// The QAM remounts the panel on every open; keep the last state so it renders at once and refreshes underneath.
let lastState: State | null = null;

// One updater per plugin load: a check or download keeps running while the QAM is closed or the page changes.
let updates: UpdateController | null = null;
const updater = () => (updates ??= new UpdateController({ check: checkForUpdates, download: performUpdate }, "fsr4injector"));
export const closeUpdates = () => { updates?.dispose(); updates = null; };

// A failed change, under the control it belongs to, until that control's next outcome (UI.md §5).
const failure = (text?: string): ReactNode => text ? <div style={{ color: colors.error }}>{text}</div> : null;

export const Content: FC = () => {
  const visible = useQuickAccessVisible();
  const [state, setStateRaw] = useState<State | null>(lastState);
  const [busy, setBusy] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState("");
  const [bulk, setBulk] = useState<{ kind: "on" | "off" | "repair"; text: string } | null>(null);
  const [error, setError] = useState("");
  const [failed, setFailed] = useState<Record<string, string>>({});
  const [page, setPage] = useState<"about" | null>(null);
  const [left, setLeft] = useState(false);  // About was just closed: its row takes the focus again.

  const setState = useCallback((s: State) => { lastState = s; setStateRaw(s); }, []);
  const mark = useCallback((at: string | number, text = "") => setFailed(f => ({ ...f, [at]: text })), []);
  // An answer's state replaces the panel's; a failed call keeps the last state and says why: a toast titled `title`
  // and, with `at`, a line under that control.
  const take = useCallback(<R extends StateResult>(r: R, title?: string, at?: string | number): R => {
    if (r.state) setState(r.state);
    if (!r.ok && title) notify(title, r.error ?? "Failed");
    if (at !== undefined) mark(at, r.ok ? "" : r.error ?? "Failed");
    return r;
  }, [setState, mark]);

  const refresh = useCallback(async () => {
    const r = await getState();
    take(r);
    setError(r.ok ? "" : r.error ?? "Failed");
  }, [take]);

  const rescan = useCallback(async (manual: boolean) => {
    setScanning(true);
    if (manual) setScanResult("");
    const r = take(await scanGames(), NAME, manual ? "rescan" : undefined);
    if (manual && r.state) setScanResult(`Found ${r.state.games.length} compatible game${r.state.games.length === 1 ? "" : "s"}.`);
    setScanning(false);
  }, [take]);

  // getState is instant; the backend scans the library at startup, so only wait for a scan if it has not finished.
  const load = useCallback(async () => {
    const r = await getState();
    take(r);
    if (!r.ok) setError(r.error ?? "Failed");
    else if (!r.state?.scanned) rescan(false);
  }, [take, rescan]);
  useEffect(() => { load(); }, [load]);

  // Poll the download's progress while it runs (the RPC itself only returns when it is finished); reads no files.
  useEffect(() => {
    if (state?.download.state !== "running") return;
    // Each tick decides from its own answer: the download_dll call may belong to a panel the QAM has since remounted.
    const t = setInterval(async () => {
      const r = await downloadProgress();
      if (!r.ok || !r.download || !lastState) return;
      if (r.download.state === "running") setState({ ...lastState, download: r.download, dll_ready: !!r.dll_ready });
      else refresh();
    }, 500);
    return () => clearInterval(t);
  }, [state?.download.state, setState, refresh]);

  const startDownload = async () => {
    if (state) setState({ ...state, download: { ...state.download, state: "running", done: 0 } });
    take(await downloadDll(), "FSR4 download failed");
  };

  // Returns whether the game ended up in the requested state; errors are shown per game.
  const apply = async (game: Game, on: boolean) => {
    try {
      const current = await readLaunchOptions(game.appid);
      const res = take(await (on ? enableGame : disableGame)(game.appid, current), game.name, game.appid);
      if (!res.ok) return false;
      if (res.launch_options !== undefined && res.launch_options !== current) {
        if (!take(await saveLaunchOptions(game.appid, res.launch_options), game.name, game.appid).ok && on) return false;
      }
      if (res.kept?.length) notify(game.name, `Left files you changed in place: ${res.kept.join(", ")}`);
      return true;
    } catch (e) {
      notify(game.name, errorText(e));
      mark(game.appid, errorText(e));
      return false;
    }
  };

  const toggle = async (game: Game, on: boolean) => {
    setBusy(game.appid);
    await apply(game, on);
    setBusy(null);
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
    const failedGames = targets.length - ok;
    const games = (n: number) => `${n} game${n === 1 ? "" : "s"}`;
    notify(NAME, (on ? `FSR4 turned on in ${games(ok)}.` : `${games(ok)} restored to how they were.`) +
      (failedGames ? ` ${games(failedGames)} could not be changed; see the messages above.` : "") +
      (skipped ? ` Skipped as possibly online: ${games(skipped)}; turn ${skipped === 1 ? "it" : "them"} on by hand if you want.` : ""));
  };

  // Repair: AMD's library must still pass its checksum, then every game that has FSR4 on is set up again.
  const repairAll = async () => {
    setBusy(-1);
    try {
      const next = take(await verifyLibrary(), NAME, "repair").state;
      if (!next) return;
      if (!next.dll_ready) {
        const damaged = "AMD's FSR4 library is missing or damaged. Download it again above, then repair.";
        notify(NAME, damaged);
        mark("repair", damaged);
        return;
      }
      const targets = next.games.filter(g => g.enabled);
      let ok = 0;
      for (const [i, g] of targets.entries()) {
        setBulk({ kind: "repair", text: `${i + 1}/${targets.length}` });
        if (await apply(g, true)) ok++;
      }
      notify(NAME, `Repaired ${ok} of ${targets.length} game${targets.length === 1 ? "" : "s"}.`);
    } finally {
      setBulk(null);
      setBusy(null);
    }
  };

  // The new setting applies at once to every game whose launch options the plugin manages.
  const setWatermark = async (on: boolean) => {
    setBusy(-1);
    try {
      const next = take(await setSetting("watermark", on), NAME, "watermark").state;
      for (const g of next?.games.filter(g => g.enabled && g.managed_options) ?? []) {
        const current = await readLaunchOptions(g.appid);
        const res = take(await applyWatermark(g.appid, current), g.name, g.appid);
        if (res.ok && res.launch_options !== undefined && res.launch_options !== current)
          take(await saveLaunchOptions(g.appid, res.launch_options), g.name, g.appid);
      }
    } catch (e) {
      notify(NAME, errorText(e));
      mark("watermark", errorText(e));
    }
    setBusy(null);
    refresh();
  };

  const copy = async (text: string) =>
    notify(NAME, (await copyText(text)) ? `Copied: ${text}` : "Copying is not available here.");

  const navigate = (next: "about" | null) => {
    setLeft(page === "about");
    setPage(next);
  };

  if (!state) return <>
    {statusPlaceholder({ title: NAME, label: `${NAME} unavailable`, error, onRetry: () => { setError(""); load(); } })}
    {/* A plugin that cannot start can still be updated. */}
    {error && <UpdateSection controller={updater()} version={__PLUGIN_VERSION__} />}
  </>;

  if (page === "about") return <Focusable onCancelActionDescription="Back" onCancelButton={e => {
    e.preventDefault();
    e.stopPropagation();  // B goes back to the main page instead of closing the menu.
    navigate(null);
  }}>
    <PageHeader title="About" back={NAME} onBack={() => navigate(null)} focus={visible} />
    <AboutPage name={NAME} version={state.version} license="BSD-3-Clause" source="github.com/Rayekkk/FSR4Injector"
      description="AMD's official FSR 4 upscaler, with the Lite model made for handhelds, in FSR 3.1 games under Proton."
      notes="The amdxc64 shim is LGPL-2.1+; its source is included in the plugin package."
      updates={updater()} home={state.home} install={`${INSTALL_HINT} Your games stay set up.`} />
  </Focusable>;

  const settings = state.settings ?? { auto_launch_options: true, watermark: false };
  const dl = state.download;
  const gpu = state.gpu;
  const canEnable = state.dll_ready && state.shim_ready && !!gpu?.model && !state.error;
  const pci = gpu ? `1002:${gpu.device.toString(16).padStart(4, "0")}` : "";
  return (
    <>
      <PanelSection title={`AMD FSR ${state.recipe.fsr}`}>
        {state.error && infoRow("Games cannot be changed", failure(state.error))}
        {gpu?.model && !gpu.verified && infoRow("Beta", "FSR 4 is not tested on this GPU yet. Report problems on GitHub.")}
        <PanelSectionRow>
          {!gpu ? (
            <Field label="No AMD GPU found" description="FSR4 Injector needs an AMD Radeon GPU." />
          ) : gpu.model ? (
            <Field label={`${gpu.arch} GPU`}
              description={`PCI ${pci}. AMD's FSR ${state.recipe.fsr} picks its ${gpu.model_name} model here.`} />
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
              <Field label="Downloading from AMD…">{MB(dl.done)} / {MB(dl.total)}</Field>
            </PanelSectionRow>
            <PanelSectionRow><ActionButton onClick={async () => take(await cancelDownload())}>Cancel</ActionButton></PanelSectionRow>
          </>
        ) : (
          <>
            <PanelSectionRow>
              <Field
                label="AMD FSR4 DLL needed"
                description={`Fetches the FSR4 library from AMD's official ${state.recipe.driver} package (about 43 MB, nothing else is kept). By downloading you accept the AMD Software EULA: ${state.eula_url}`}
              />
            </PanelSectionRow>
            {dl.state === "error" && infoRow("Last attempt failed", dl.error)}
            <PanelSectionRow><ActionButton onClick={startDownload}>Accept and download</ActionButton></PanelSectionRow>
          </>
        )}
        {!state.shim_ready && infoRow("Plugin files incomplete", "bin/amdxc64.dll is missing. Reinstall the plugin.")}
      </PanelSection>

      <PanelSection title="Games with FSR 3.1+">
        {state.games.length === 0 && infoRow(!state.scanned || scanning ? "Scanning your library…"
          : "No compatible games found", !state.scanned || scanning ? undefined : "Install a game with FSR 3.1 or newer, then rescan your library.")}
        {state.games.map(g => (
          <PanelSectionRow key={g.appid}>
            <ToggleField
              label={g.name}
              description={<>
                {g.enabled ? `${VERDICT_LABEL[g.verdict]}. ${g.reason}`
                  : !g.anticheat && onlineStatus(g.appid) === "online"
                    ? "Online multiplayer: skipped by Turn on all. Turning it on is at your own risk." : null}
                {g.anticheat && <div style={{ color: colors.error }}>{ANTICHEAT_WARNING}</div>}
                {failure(failed[g.appid])}
              </>}
              checked={g.enabled}
              disabled={busy !== null || (!g.enabled && !canEnable)}
              onChange={on => toggle(g, on)}
            />
          </PanelSectionRow>
        ))}
        <PanelSectionRow>
          <ActionButton disabled={busy !== null || scanning} onClick={() => rescan(true)}
            description={scanning ? undefined : failure(failed.rescan) || scanResult || undefined}>
            {scanning ? "Scanning…" : "Rescan library"}
          </ActionButton>
        </PanelSectionRow>
        {canEnable && state.games.some(g => !g.enabled && !g.anticheat) && (
          <PanelSectionRow>
            <ActionButton disabled={busy !== null} onClick={() => applyAll(true)}
              description="Sets up every compatible game in the list. Online games and games with anti-cheat are skipped.">
              {bulk?.kind === "on" ? `Turning on… ${bulk.text}` : "Turn on FSR4 in all games"}
            </ActionButton>
          </PanelSectionRow>
        )}
        {state.games.some(g => g.enabled) && (
          <PanelSectionRow>
            <ActionButton disabled={busy !== null} onClick={() => applyAll(false)}
              description="Removes the plugin's files and launch option from every game, leaving them as they were. Do this before uninstalling.">
              {bulk?.kind === "off" ? `Restoring… ${bulk.text}` : "Turn off FSR4 and restore all games"}
            </ActionButton>
          </PanelSectionRow>
        )}
        {state.games.some(g => g.enabled) && (
          <PanelSectionRow>
            <ActionButton disabled={busy !== null} onClick={repairAll}
              description={<>Checks AMD's library and puts the plugin's files and launch option back in every game that has
                FSR4 on, for example after a game update or Steam's file check.{failure(failed.repair)}</>}>
              {bulk?.kind === "repair" ? `Repairing… ${bulk.text}` : "Repair FSR4 in all games"}
            </ActionButton>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Launch options">
        <PanelSectionRow>
          <ToggleField
            label="Add launch option automatically"
            description={<>{`Turning FSR4 on for a game adds ${state.copy_options.plain} to its launch options. ` +
              "Off: add it yourself; the plugin then leaves the game's launch options alone."}{failure(failed.auto_launch_options)}</>}
            checked={settings.auto_launch_options}
            disabled={busy !== null}
            onChange={async on => take(await setSetting("auto_launch_options", on), NAME, "auto_launch_options")}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Show AMD's FSR4 watermark"
            description={<>Also adds FSR_WATERMARK=1, so AMD's library shows which FSR 4 model runs. Applies to the games set
              up above at once.{failure(failed.watermark)}</>}
            checked={settings.auto_launch_options && settings.watermark}
            disabled={busy !== null || !settings.auto_launch_options}
            onChange={setWatermark}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ActionButton onClick={() => copy(state.copy_options.plain)} description={state.copy_options.plain}>
            Copy launch options
          </ActionButton>
        </PanelSectionRow>
        <PanelSectionRow>
          <ActionButton onClick={() => copy(state.copy_options.watermark)} description={state.copy_options.watermark}>
            Copy launch options + watermark
          </ActionButton>
        </PanelSectionRow>
        {hasLaunchOptionsPlugin() && (
          <PanelSectionRow>
            <ActionButton onClick={() => offerToLaunchOptionsPlugin(state.copy_options)}
              description={"Adds FSR4 Injector and AMD FSR4 watermark to Decky Launch Options, to switch per game there. " +
                "Then turn off Add launch option automatically above; FSR4 still has to be on here for the game's files."}>
              Add to Decky Launch Options
            </ActionButton>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection>
        <SectionLink title="About" description={`Version ${state.version} · updates`} focus={visible && left}
          icon={<><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10h.01" /></>} onOpen={() => navigate("about")} />
      </PanelSection>
    </>
  );
};
