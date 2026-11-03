// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

import { definePlugin } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { off, readLaunchOptions, sessionCheck, sessionEnded, sessionStarted, startupNotice } from "./api";
import { closeUpdates, Content } from "./panel";
import { notify } from "./ui";

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
  startupNotice().then(r => { if (r.message) notify("FSR4 Injector", r.message); });

  // With "Tell me when FSR4 runs" on, a running game's status is read every few seconds until FSR 4 runs in it.
  // Only success is told during the game; failures wait for the verdict at its end.
  const watching = new Map<number, number | undefined>();  // appid → pending check
  const unwatch = (appid: number) => {
    window.clearTimeout(watching.get(appid));
    watching.delete(appid);
  };
  const check = (appid: number) => watching.set(appid, window.setTimeout(async () => {
    const res = await sessionCheck(appid);
    if (!watching.has(appid)) return;  // the game ended meanwhile
    if (!res.running) return void check(appid);
    watching.delete(appid);
    notify("FSR4 active", `${res.running} is running.`);
  }, 4000));

  // Never fail silently: when a game we manage exits, tell the user if FSR4 was requested but not active.
  // Launch options are passed on exit so a session our DLL missed can name the cause (e.g. another tool rewrote them).
  // A backend that is restarting answers ok: false; the panel shows the same verdict next time it opens.
  const lifetime = SteamClient.GameSessions.RegisterForAppLifetimeNotifications(async n => {
    if (n?.bRunning) {
      watching.set(n.unAppID, undefined);
      const res = await sessionStarted(n.unAppID);
      if (res.watch && watching.has(n.unAppID)) check(n.unAppID);
      else watching.delete(n.unAppID);
      return;
    }
    unwatch(n.unAppID);
    const options = await readLaunchOptions(n.unAppID).catch(() => "");
    const res = await sessionEnded(n.unAppID, options);
    if (res.managed && res.verdict === "failed") notify("FSR4 not active", res.reason ?? "");
  });

  return {
    name: "FSR4 Injector",
    titleView: <div className={staticClasses.Title}>FSR4 Injector</div>,
    content: <Content />,
    icon: <Fsr4Icon />,
    onDismount() {
      off(lifetime);
      [...watching.keys()].forEach(unwatch);
      closeUpdates();
    },
  };
});
