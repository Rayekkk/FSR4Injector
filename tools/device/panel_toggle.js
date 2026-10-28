(async () => {
  // Same steps as the panel's toggle(): read options from Steam, ask the backend, apply its result.
  const appid = __APPID__, on = __ON__;
  const api = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit.connect(1, "FSR4 Injector");
  const read = () => new Promise((resolve, reject) => {
    let done = false;
    const timer = setTimeout(() => { if (!done) { done = true; reg?.unregister?.(); reject(new Error("no app details")); } }, 3000);
    const reg = SteamClient.Apps.RegisterForAppDetails(appid, d => {
      if (done) return;
      done = true; clearTimeout(timer); setTimeout(() => reg?.unregister?.(), 0);
      resolve(d?.strLaunchOptions ?? "");
    });
  });
  const before = await read();
  await api.call("scan_games");
  const res = await api.call(on ? "enable_game" : "disable_game", appid, before);
  let saved = null;
  if (res.ok && res.launch_options !== undefined && res.launch_options !== before) {
    SteamClient.Apps.SetAppLaunchOptions(appid, res.launch_options);
    saved = await api.call("launch_options_saved", appid, await read());
  }
  const after = await read();
  return JSON.stringify({ before, ok: res.ok, error: res.error, launch_options: res.launch_options, saved, after });
})()
