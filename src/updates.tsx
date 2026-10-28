// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The Updates section: DeckyKit's shared updater checks GitHub and saves the verified release ZIP to Downloads; the
// user installs it by hand.
import { ButtonItem, Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { FC, useState } from "react";
import { checkForUpdates, performUpdate, UpdateInfo } from "./api";

// Survives the QAM remounting the panel, like the panel state.
let updateView: { info: UpdateInfo | null; checking: boolean; downloading: boolean; path: string | null } =
  { info: null, checking: false, downloading: false, path: null };

const versionTag = (value: string) => (
  <span style={{ fontWeight: 700, color: "var(--gpColor-White, #fff)", background: "rgba(102,192,244,.18)", borderRadius: "4px", padding: "1px 6px" }}>
    v{value}
  </span>
);

export const Updates: FC<{ version: string }> = ({ version }) => {
  const [view, setViewRaw] = useState(updateView);
  const setView = (next: Partial<typeof updateView>) => { updateView = { ...updateView, ...next }; setViewRaw(updateView); };
  const { info, checking, downloading, path } = view;
  const problem = info && !info.ok ? info.error ?? "Unknown error" : "";

  const check = async () => {
    if (updateView.checking || updateView.downloading) return;
    setView({ checking: true, info: null, path: null });
    setView({ info: await checkForUpdates(), checking: false });
  };

  const download = async () => {
    const expected = updateView.info?.latest_version;
    if (!expected || updateView.checking || updateView.downloading) return;
    setView({ downloading: true });
    const res = await performUpdate(expected);
    if (res.ok && res.path && res.version === expected) setView({ path: res.path });
    else setView({ info: { ...(updateView.info ?? {}), ok: false, error: res.error ?? "The download did not finish." } });
    setView({ downloading: false });
  };

  return (
    <PanelSection title="Updates">
      <PanelSectionRow>
        <div style={{ fontSize: "12px", color: "var(--gpColor-TextMuted, rgba(255,255,255,.6))", overflowWrap: "anywhere" }}>
          Installed: {versionTag(info?.current_version ?? version)}
          {info?.latest_version && !problem && <>{" · "}Latest: {versionTag(info.latest_version)}</>}
        </div>
      </PanelSectionRow>
      {problem && (
        <PanelSectionRow>
          <div style={{ padding: "8px", borderRadius: "4px", background: "rgba(248,113,113,.14)", color: "var(--gpColor-Red, #f87171)", overflowWrap: "anywhere" }}>
            {problem}
          </div>
        </PanelSectionRow>
      )}
      {info && !problem && !path && (info.message || !info.update_available) && (
        <PanelSectionRow>
          <div style={{ fontSize: "12px", color: info.message ? "var(--gpColor-TextMuted, rgba(255,255,255,.6))" : "var(--gpColor-Green, #4ade80)", overflowWrap: "anywhere" }}>
            {info.message || "Up to date"}
          </div>
        </PanelSectionRow>
      )}
      {info?.download_available && !problem && !path && (
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
