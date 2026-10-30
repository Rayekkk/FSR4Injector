(async () => {
  // Same steps as the panel's toggle(): read options from Steam, ask the backend, apply its result.
  const appid = __APPID__, on = __ON__;
  const api = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit.connect(1, "FSR4 Injector");
  // like api.ts readLaunchOptions: a read-back waits up to 1 s for the written value (non-Steam shortcuts lag)
  const read = expected => new Promise((resolve, reject) => {
    let done = false, last;
    const finish = () => {
      if (done) return;
      done = true; clearTimeout(timer); setTimeout(() => reg?.unregister?.(), 0);
      last === undefined ? reject(new Error("no app details")) : resolve(last);
    };
    const timer = setTimeout(finish, 3000);
    const reg = SteamClient.Apps.RegisterForAppDetails(appid, d => {
      if (done) return;
      last = d?.strLaunchOptions ?? "";
      if (expected === undefined || last === expected) finish(); else setTimeout(finish, 1000);
    });
  });
  const before = await read();
  await api.call("scan_games");
  const res = await api.call(on ? "enable_game" : "disable_game", appid, before);
  let saved = null;
  if (res.ok && res.launch_options !== undefined && res.launch_options !== before) {
    SteamClient.Apps.SetAppLaunchOptions(appid, res.launch_options);
    saved = await api.call("launch_options_saved", appid, await read(res.launch_options));
  }
  const after = await read();
  return JSON.stringify({ before, ok: res.ok, error: res.error, launch_options: res.launch_options, saved, after });
})()
