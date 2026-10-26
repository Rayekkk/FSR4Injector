// SPDX-License-Identifier: BSD-3-Clause
// Execute the actual TSX with controlled hooks, RPC completion and timers (same approach as the Companion plugins).
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), ts = require(path.join(root, 'node_modules/typescript'));
const settle = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };

function harness() {
  const slots = [], effects = new Map(), pending = [], calls = [], toasts = [], callbacks = {}, applied = [], copied = [], events = [];
  const window = { hasDeckyLaunchOptions: false, dispatchEvent: e => events.push(e) };
  let cursor = 0;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const hooks = {
    useState(value) { const i = cursor++; if (!(i in slots)) slots[i] = typeof value === 'function' ? value() : value;
      return [slots[i], v => { slots[i] = typeof v === 'function' ? v(slots[i]) : v; }]; },
    useCallback(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { fn, deps }; return slots[i].fn; },
    useEffect(fn, deps) { const i = cursor++, old = effects.get(i); if (!old || !same(old.deps, deps)) pending.push(() => {
      old?.cleanup?.(); effects.set(i, { deps, cleanup: fn() });
    }); },
  };
  // Function components (Updates) render in place, so their hooks run in a stable order within Content's render.
  const el = (type, props) => (typeof type === 'function' ? type(props) : { type, props });
  const jsx = { jsx: el, jsxs: el, Fragment: 'Fragment' };
  const callable = name => (...args) => new Promise((resolve, reject) => calls.push({ name, args, resolve, reject, settled: false }));
  // Steam store categories per app; 36/38 are Online PvP / Online Co-op. Apps not listed have no data.
  const categories = { 1817070: [2, 22], 2: [2, 28], 4: [2, 22], 5: [2, 1, 36, 38] };
  const appStore = { GetAppOverviewByAppID: id => (id in categories ? { store_category: categories[id] } : null) };
  const SteamClient = {
    GameSessions: { RegisterForAppLifetimeNotifications(fn) { callbacks.lifetime = fn; return { unregister() {} }; } },
    Apps: {
      RegisterForAppDetails(appid, fn) { Promise.resolve().then(() => fn({ strLaunchOptions: '~/.dlo/run %command%' })); return { unregister() {} }; },
      SetAppLaunchOptions(appid, value) { applied.push([appid, value]); },
    },
  };
  const source = fs.readFileSync(path.join(root, 'src', 'index.tsx'), 'utf8') + '\nexport { Content };';
  const output = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const mod = { exports: {} };
  vm.runInNewContext(output, {
    module: mod, exports: mod.exports, console, SteamClient, appStore, setTimeout, clearTimeout, setInterval, clearInterval,
    navigator: { clipboard: { writeText: async t => { copied.push(t); } } },
    window, CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
    require(name) {
      if (name === 'react') return hooks;
      if (name === 'react/jsx-runtime') return jsx;
      if (name === '@decky/api') return { callable, definePlugin: fn => fn, toaster: { toast: v => toasts.push(v) } };
      if (name === '@decky/ui') return new Proxy({}, { get: (object, key) => key });
      throw Error(name);
    },
  });
  const plugin = mod.exports;
  const render = () => { cursor = 0; const tree = plugin.Content({}); pending.splice(0).forEach(fn => fn()); return tree; };
  return {
    plugin, render, calls, toasts, callbacks, applied, copied, events, window,
    remount() { for (const e of effects.values()) e.cleanup?.(); effects.clear(); slots.length = 0; pending.length = 0; return render(); },
    respond(name, value) {
      const call = calls.find(c => c.name === name && !c.settled); assert.ok(call, `pending ${name}`);
      call.settled = true; call.resolve(value); return call;
    },
    pending(name) { return calls.some(c => c.name === name && !c.settled); },
  };
}

function all(node, out = []) {
  if (Array.isArray(node)) node.forEach(n => all(n, out));
  else if (node && typeof node === 'object') { out.push(node); all(node.props?.children, out); }
  return out;
}
const byType = (tree, type) => all(tree).filter(n => n.type === type);
const strings = node => all(node).flatMap(n => [].concat(n.props?.children ?? []).filter(c => typeof c === 'string'));
const desc = props => typeof props.description === 'object' && props.description ? strings(props.description).join(' ') : props.description ?? '';
const text = node => all(node).flatMap(n => [n.props?.label, n.props?.description ? desc(n.props) : null, typeof n.props?.children === 'string' ? n.props.children : null]).filter(Boolean).join(' | ');
const button = (tree, label) => byType(tree, 'ButtonItem').find(b => [].concat(b.props.children).includes(label));

const game = { appid: 1817070, name: 'Spider-Man', target_dir: '/g', anticheat: false, enabled: false, verdict: 'unknown', reason: '' };
const gpu890 = { device: 0x150e, family: 150, rev: 20, arch: 'RDNA 3.5', model: 'INT8_LITE', model_name: 'INT8 Lite', verified: true };
const state = (over = {}) => ({
  version: '1.0.0', dll_ready: true, shim_ready: true, gpu: gpu890,
  recipe: { driver: 'Adrenalin 26.10.1', fsr: '4.1.2', dll_size: 1 }, eula_url: 'https://x',
  download: { state: 'idle', done: 0, total: 1, error: '' }, scanned: true, games: [game],
  settings: { auto_launch_options: true, watermark: false },
  copy_options: { plain: 'WINEDLLOVERRIDES=amdxc64=n,b %command%', watermark: 'WINEDLLOVERRIDES=amdxc64=n,b FSR_WATERMARK=1 %command%' },
  ...over,
});

(async () => {
  const h = harness();

  // First open ever: nothing cached yet, a spinner until the backend answers.
  assert.equal(byType(h.render(), 'Spinner').length, 1);
  h.respond('get_state', state());
  await settle();
  assert.ok(!h.pending('scan_games'), 'the backend already scanned at startup; opening the panel must not rescan');
  assert.match(text(h.render()), /Spider-Man/);

  // Every later open renders the last state at once, then refreshes underneath.
  let tree = h.remount();
  assert.equal(byType(tree, 'Spinner').length, 0, 'reopening the panel must not show a spinner');
  assert.match(text(tree), /Spider-Man/);
  h.respond('get_state', state());
  await settle();

  // Backend still scanning after startup: say so instead of "No compatible games found".
  h.remount();
  h.respond('get_state', state({ scanned: false, games: [] }));
  await settle();
  assert.match(text(h.render()), /Scanning your library/);
  h.respond('scan_games', state());
  await settle();

  // Rescan gives feedback while it runs and a result after.
  tree = h.render();
  button(tree, 'Rescan library').props.onClick();
  tree = h.render();
  const busy = button(tree, 'Scanning…');
  assert.ok(busy && busy.props.disabled, 'Rescan shows "Scanning…" and is disabled while running');
  h.respond('scan_games', state({ games: [game, { ...game, appid: 2, name: 'E33' }] }));
  await settle();
  tree = h.render();
  assert.equal(button(tree, 'Rescan library').props.description, 'Found 2 compatible games.');

  // Toggle: reads Steam's launch options, applies what the backend computed.
  const toggle = byType(tree, 'ToggleField').find(t => t.props.label === 'Spider-Man');
  toggle.props.onChange(true);
  await settle();
  const call = h.respond('enable_game', { ok: true, launch_options: 'WINEDLLOVERRIDES=amdxc64=n,b ~/.dlo/run %command%' });
  assert.deepEqual(call.args, [1817070, '~/.dlo/run %command%']);
  await settle();
  assert.deepEqual(h.applied, [[1817070, 'WINEDLLOVERRIDES=amdxc64=n,b ~/.dlo/run %command%']]);

  // Turn on in all games: every compatible offline game, one at a time, with progress and a summary. Anti-cheat
  // games, online games (Steam categories) and games Steam has no data for are skipped.
  h.applied.length = 0;
  h.respond('get_state', state({ games: [
    { ...game, enabled: true, verdict: 'ok' }, { ...game, appid: 2, name: 'E33' },
    { ...game, appid: 3, name: 'Anti-cheat', anticheat: true }, { ...game, appid: 4, name: 'Hitman' },
    { ...game, appid: 5, name: 'Forza' }, { ...game, appid: 6, name: 'No data' } ] }));
  await settle();
  tree = h.render();
  const forza = byType(tree, 'ToggleField').find(t => t.props.label === 'Forza');
  assert.match(desc(forza.props), /Online multiplayer: skipped by Turn on all/);
  const ac = byType(tree, 'ToggleField').find(t => t.props.label === 'Anti-cheat');
  assert.ok(!ac.props.disabled, 'an anti-cheat game can be turned on by hand');
  assert.ok(all(ac.props.description).some(n => n.props?.style?.color && strings(n).join('').includes('Anti-cheat detected')), 'red warning under the switch');
  assert.ok(!forza.props.disabled, 'an online game can still be turned on by hand');
  assert.equal(desc(byType(tree, 'ToggleField').find(t => t.props.label === 'No data').props), '');
  assert.ok(button(tree, 'Turn off FSR4 and restore all games'), 'restore-all is offered when a game is on');
  button(tree, 'Turn on FSR4 in all games').props.onClick();
  await settle();
  assert.ok(button(h.render(), 'Turning on… 1/2'), 'progress shows on the button that runs');
  assert.ok(button(h.render(), 'Turn off FSR4 and restore all games').props.disabled);
  assert.equal(h.respond('enable_game', { ok: true, launch_options: 'T %command%' }).args[0], 2);
  await settle();
  assert.equal(h.respond('enable_game', { ok: false, error: 'not ours' }).args[0], 4);
  await settle();
  assert.ok(!h.pending('enable_game'), 'anti-cheat, online, unknown and already-enabled games are skipped');
  assert.equal(h.toasts.at(-1).body, 'FSR4 turned on in 1 game. 1 game could not be changed; see the messages above. '
    + 'Skipped as possibly online: 2 games; turn them on by hand if you want.');
  h.respond('get_state', state({ games: [{ ...game, enabled: true }, { ...game, appid: 2, name: 'E33', enabled: true }] }));
  await settle();

  // Turn off and restore all games.
  button(h.render(), 'Turn off FSR4 and restore all games').props.onClick();
  await settle();
  assert.ok(button(h.render(), 'Restoring… 1/2'));
  for (const id of [1817070, 2]) {
    assert.equal(h.respond('disable_game', { ok: true, launch_options: '~/.dlo/run %command%', kept: [] }).args[0], id);
    await settle();
  }
  assert.equal(h.toasts.at(-1).body, '2 games restored to how they were.');
  h.respond('get_state', state());
  await settle();

  // Repair: re-checks AMD's library, then sets every enabled game up again; a damaged library asks for a download.
  h.remount();
  h.respond('get_state', state({ games: [{ ...game, enabled: true }, { ...game, appid: 2, name: 'E33' }] }));
  await settle();
  button(h.render(), 'Repair FSR4 in all games').props.onClick();
  await settle();
  h.respond('verify_library', state({ games: [{ ...game, enabled: true }, { ...game, appid: 2, name: 'E33' }] }));
  await settle();
  assert.ok(button(h.render(), 'Repairing… 1/1'), 'repair shows its own progress');
  assert.equal(h.respond('enable_game', { ok: true, launch_options: 'T %command%' }).args[0], 1817070);
  await settle();
  assert.ok(!h.pending('enable_game'), 'only games that have FSR4 on are repaired');
  assert.equal(h.toasts.at(-1).body, 'Repaired 1 of 1 game.');
  h.respond('get_state', state({ games: [{ ...game, enabled: true }] }));
  await settle();
  button(h.render(), 'Repair FSR4 in all games').props.onClick();
  await settle();
  h.respond('verify_library', state({ dll_ready: false, games: [{ ...game, enabled: true }] }));
  await settle();
  assert.ok(!h.pending('enable_game'), 'nothing is copied from a damaged library');
  assert.match(h.toasts.at(-1).body, /missing or damaged/);
  h.respond('get_state', state());
  await settle();

  // Launch options section: automatic launch option (default on), the watermark switch tied to it, copy buttons.
  h.remount();
  h.respond('get_state', state({ games: [{ ...game, enabled: true, managed_options: true }, { ...game, appid: 2, name: 'E33', enabled: true }] }));
  await settle();
  tree = h.render();
  const sw = label => byType(tree, 'ToggleField').find(t => t.props.label === label).props;
  assert.equal(sw('Add launch option automatically').checked, true);
  assert.equal(sw("Show AMD's FSR4 watermark").disabled, false);
  sw("Show AMD's FSR4 watermark").onChange(true);
  await settle();
  assert.deepEqual(h.respond('set_setting', state({ settings: { auto_launch_options: true, watermark: true },
    games: [{ ...game, enabled: true, managed_options: true }, { ...game, appid: 2, name: 'E33', enabled: true }] })).args, ['watermark', true]);
  await settle();
  h.applied.length = 0;
  const wm = h.respond('apply_watermark', { ok: true, launch_options: 'WINEDLLOVERRIDES=amdxc64=n,b FSR_WATERMARK=1 ~/.dlo/run %command%' });
  assert.deepEqual(wm.args, [1817070, '~/.dlo/run %command%']);
  await settle();
  assert.ok(!h.pending('apply_watermark'), 'only games whose launch options the plugin manages are changed');
  assert.deepEqual(h.applied, [[1817070, 'WINEDLLOVERRIDES=amdxc64=n,b FSR_WATERMARK=1 ~/.dlo/run %command%']]);
  h.respond('get_state', state({ settings: { auto_launch_options: false, watermark: true } }));
  await settle();
  tree = h.render();
  assert.equal(sw("Show AMD's FSR4 watermark").disabled, true, 'watermark is greyed out without the automatic launch option');
  assert.equal(sw("Show AMD's FSR4 watermark").checked, false);
  button(tree, 'Copy launch options').props.onClick();
  await settle();
  button(tree, 'Copy launch options + watermark').props.onClick();
  await settle();
  assert.deepEqual(h.copied, ['WINEDLLOVERRIDES=amdxc64=n,b %command%', 'WINEDLLOVERRIDES=amdxc64=n,b FSR_WATERMARK=1 %command%']);
  assert.match(h.toasts.at(-1).body, /^Copied: /);
  // Decky Launch Options: the button shows only when that plugin is there, and offers both entries with stable ids
  assert.ok(!button(tree, 'Add to Decky Launch Options'));
  h.window.hasDeckyLaunchOptions = true;
  tree = h.render();
  button(tree, 'Add to Decky Launch Options').props.onClick();
  assert.equal(h.events.at(-1).type, 'dlo-add-launch-options');
  assert.deepEqual(JSON.parse(JSON.stringify(h.events.at(-1).detail.map(o => [o.id, o.group, o.name, o.on, o.off, o.enableGlobally]))), [
    ['fsr4-injector', 'FSR4 Injector', 'FSR4 Injector', 'WINEDLLOVERRIDES=amdxc64=n,b', '', false],
    ['fsr4-injector-watermark', 'FSR4 Injector', 'AMD FSR4 watermark', 'FSR_WATERMARK=1', '', false],
  ]);
  h.window.hasDeckyLaunchOptions = false;
  h.remount();
  h.respond('get_state', state());
  await settle();

  // About and Updates at the bottom: check, then download the verified ZIP and say how to install it.
  tree = h.render();
  assert.match(text(tree), /FSR4 Injector · v1\.0\.0/);
  button(tree, 'Check for updates').props.onClick();
  await settle();
  assert.ok(button(h.render(), 'Checking…').props.disabled);
  h.respond('check_for_updates', { current_version: '1.0.0', latest_version: '1.1.0', update_available: true, asset_name: 'FSR4Injector-1.1.0.zip' });
  await settle();
  button(h.render(), 'Download v1.1.0').props.onClick();
  await settle();
  assert.deepEqual(h.respond('perform_update', { path: '/home/deck/Downloads/FSR4Injector-1.1.0.zip', version: '1.1.0' }).args, ['1.1.0']);
  await settle();
  assert.match(text(h.render()), /Update downloaded/);
  button(h.render(), 'Check for updates').props.onClick();
  await settle();
  h.respond('check_for_updates', { current_version: '1.0.0', update_available: false, error: "GitHub's request limit was reached. Try again later." });
  await settle();
  assert.ok(all(h.render()).some(n => strings(n).join('').includes('request limit')), 'update errors are shown');

  // GPU line: verified, beta, and a GPU AMD has no model for (switches locked, nothing to turn on).
  tree = h.render();
  assert.match(text(tree), /RDNA 3\.5 GPU \| PCI 1002:150e\. AMD's FSR 4\.1\.2 picks its INT8 Lite model here\./);
  assert.doesNotMatch(text(tree), /Beta/);
  h.remount();
  h.respond('get_state', state({ gpu: { ...gpu890, device: 0x163f, family: 144, rev: 1, arch: 'RDNA 2 APU (Van Gogh)', verified: false } }));
  await settle();
  assert.match(text(h.render()), /Beta: not tested on this GPU yet/);
  h.remount();
  h.respond('get_state', state({ gpu: { ...gpu890, device: 0x15bf, family: 148, arch: 'RDNA 3 APU', model: null, model_name: '' } }));
  await settle();
  tree = h.render();
  assert.match(text(tree), /GPU not supported \| AMD's FSR 4 has no model for this GPU \(RDNA 3 APU, PCI 1002:15bf\)/);
  assert.ok(byType(tree, 'ToggleField').filter(t => t.props.label === game.name).every(t => t.props.disabled), 'nothing can be turned on without a model');
  assert.ok(!button(tree, 'Turn on FSR4 in all games'));
  h.remount();
  h.respond('get_state', state());
  await settle();

  // Plugin load: SteamOS update notice, and a warning when a session ended without FSR4.
  h.plugin.default();
  h.respond('startup_notice', { message: 'SteamOS was updated (a → b).' });
  await settle();
  assert.equal(h.toasts.at(-1).body, 'SteamOS was updated (a → b).');
  h.callbacks.lifetime({ unAppID: 1817070, bRunning: true });
  await settle();
  h.respond('session_started', { managed: true });
  h.callbacks.lifetime({ unAppID: 1817070, bRunning: false });
  await settle();
  const ended = h.respond('session_ended', { managed: true, verdict: 'failed', reason: 'fell back to FSR3' });
  assert.deepEqual(ended.args, [1817070, '~/.dlo/run %command%']);
  await settle();
  assert.equal(h.toasts.at(-1).title, 'FSR4 not active');

  console.log('Panel verified: instant reopen, scan feedback, toggle flow, launch option settings and notifications.');
})().catch(e => { console.error(e); process.exit(1); });
