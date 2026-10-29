// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The Quick Access panel: AMD's library, the games, launch options, about and updates.
import { ButtonItem, Field, PanelSection, PanelSectionRow, Spinner, ToggleField } from "@decky/ui";
import { FC, useCallback, useEffect, useState } from "react";
import {
  applyWatermark, cancelDownload, disableGame, downloadDll, downloadProgress, enableGame, Game, getState, notify,
  readLaunchOptions, saveLaunchOptions, scanGames, setSetting, State, StateResult, verifyLibrary,
} from "./api";
import {
  ANTICHEAT_WARNING, copyText, hasLaunchOptionsPlugin, MiB, offerToLaunchOptionsPlugin, onlineStatus, VERDICT_LABEL,
} from "./shared";
import { errorText } from "./result";
import { Updates } from "./updates";

// The QAM remounts the panel on every open; keep the last state so it renders at once and refreshes underneath.
let lastState: State | null = null;

export const Content: FC = () => {
  const [state, setStateRaw] = useState<State | null>(lastState);
  const [busy, setBusy] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState("");
  const [bulk, setBulk] = useState<{ kind: "on" | "off" | "repair"; text: string } | null>(null);
  const [error, setError] = useState("");

  const setState = useCallback((s: State) => { lastState = s; setStateRaw(s); }, []);
  // An answer's state replaces the panel's; a failed call keeps the last state and says why.
  const take = useCallback(<R extends StateResult>(r: R, title?: string): R => {
    if (r.state) setState(r.state);
    if (!r.ok && title) notify(title, r.error ?? "Failed");
    return r;
  }, [setState]);

  const refresh = useCallback(async () => {
    const r = await getState();
    take(r);
    setError(r.ok ? "" : r.error ?? "Failed");
  }, [take]);

  const rescan = useCallback(async (manual: boolean) => {
    setScanning(true);
    if (manual) setScanResult("");
    const r = take(await scanGames(), "FSR4 Injector");
    if (manual && r.state) setScanResult(`Found ${r.state.games.length} compatible game${r.state.games.length === 1 ? "" : "s"}.`);
    setScanning(false);
  }, [take]);

  // getState is instant; the backend scans the library at startup, so only wait for a scan if it has not finished.
  useEffect(() => {
    getState().then(r => {
      take(r);
      if (!r.ok) setError(r.error ?? "Failed");
      else if (!r.state?.scanned) rescan(false);
    });
  }, [take, rescan]);

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
      const res = take(await (on ? enableGame : disableGame)(game.appid, current), game.name);
      if (!res.ok) return false;
      if (res.launch_options !== undefined && res.launch_options !== current) {
        if (!take(await saveLaunchOptions(game.appid, res.launch_options), game.name).ok && on) return false;
      }
      if (res.kept?.length) notify(game.name, `Left files you changed in place: ${res.kept.join(", ")}`);
      return true;
    } catch (e) {
      notify(game.name, errorText(e));
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
    const failed = targets.length - ok;
    const games = (n: number) => `${n} game${n === 1 ? "" : "s"}`;
    notify("FSR4 Injector", (on ? `FSR4 turned on in ${games(ok)}.` : `${games(ok)} restored to how they were.`) +
      (failed ? ` ${games(failed)} could not be changed; see the messages above.` : "") +
      (skipped ? ` Skipped as possibly online: ${games(skipped)}; turn ${skipped === 1 ? "it" : "them"} on by hand if you want.` : ""));
  };

  // Repair: AMD's library must still pass its checksum, then every game that has FSR4 on is set up again.
  const repairAll = async () => {
    setBusy(-1);
    try {
      const next = take(await verifyLibrary(), "FSR4 Injector").state;
      if (!next) return;
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
    } finally {
      setBulk(null);
      setBusy(null);
    }
  };

  // The new setting applies at once to every game whose launch options the plugin manages.
  const setWatermark = async (on: boolean) => {
    setBusy(-1);
    try {
      const next = take(await setSetting("watermark", on), "FSR4 Injector").state;
      for (const g of next?.games.filter(g => g.enabled && g.managed_options) ?? []) {
        const current = await readLaunchOptions(g.appid);
        const res = take(await applyWatermark(g.appid, current), g.name);
        if (res.ok && res.launch_options !== undefined && res.launch_options !== current)
          take(await saveLaunchOptions(g.appid, res.launch_options), g.name);
      }
    } catch (e) {
      notify("FSR4 Injector", errorText(e));
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
  const canEnable = state.dll_ready && state.shim_ready && !!gpu?.model && !state.error;
  const pci = gpu ? `1002:${gpu.device.toString(16).padStart(4, "0")}` : "";
  return (
    <>
      <PanelSection title={`AMD FSR ${state.recipe.fsr}`}>
        {state.error && (
          <PanelSectionRow><Field label="Games cannot be changed" description={<div style={{ color: "#ff5c5c" }}>{state.error}</div>} /></PanelSectionRow>
        )}
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
            <PanelSectionRow><ButtonItem layout="below" onClick={async () => take(await cancelDownload())}>Cancel</ButtonItem></PanelSectionRow>
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
            onChange={async on => take(await setSetting("auto_launch_options", on), "FSR4 Injector")}
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
                "Then turn off Add launch option automatically above; FSR4 still has to be on here for the game's files."}>
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
