// SPDX-License-Identifier: BSD-3-Clause
// Execute the actual TSX with controlled hooks, RPC completion and timers (same approach as the Companion plugins).
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), ts = require(path.join(root, 'node_modules/typescript'));
const settle = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };

function harness() {
  const slots = [], effects = new Map(), pending = [], calls = [], toasts = [], callbacks = {}, applied = [];
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
  const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'Fragment' };
  const callable = name => (...args) => new Promise((resolve, reject) => calls.push({ name, args, resolve, reject, settled: false }));
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
    module: mod, exports: mod.exports, console, SteamClient, setTimeout, clearTimeout, setInterval, clearInterval,
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
    plugin, render, calls, toasts, callbacks, applied,
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
const text = node => all(node).flatMap(n => [n.props?.label, n.props?.description, typeof n.props?.children === 'string' ? n.props.children : null]).filter(Boolean).join(' | ');
const button = (tree, label) => byType(tree, 'ButtonItem').find(b => [].concat(b.props.children).includes(label));

const game = { appid: 1817070, name: 'Spider-Man', target_dir: '/g', anticheat: false, enabled: false, verdict: 'unknown', reason: '' };
const state = (over = {}) => ({
  dll_ready: true, shim_ready: true, recipe: { driver: 'Adrenalin 26.10.1', fsr: '4.1.2', dll_size: 1 }, eula_url: 'https://x',
  download: { state: 'idle', done: 0, total: 1, error: '' }, scanned: true, games: [game], ...over,
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

  // Turn on in all games: every compatible game except anti-cheat ones, one at a time, with progress and a summary.
  h.applied.length = 0;
  h.respond('get_state', state({ games: [
    { ...game, enabled: true, verdict: 'ok' }, { ...game, appid: 2, name: 'E33' },
    { ...game, appid: 3, name: 'Online', anticheat: true }, { ...game, appid: 4, name: 'Hitman' } ] }));
  await settle();
  tree = h.render();
  assert.ok(button(tree, 'Turn off FSR4 and restore all games'), 'restore-all is offered when a game is on');
  button(tree, 'Turn on FSR4 in all games').props.onClick();
  await settle();
  assert.ok(button(h.render(), 'Turning on… 1/2'), 'progress shows on the button that runs');
  assert.ok(button(h.render(), 'Turn off FSR4 and restore all games').props.disabled);
  assert.equal(h.respond('enable_game', { ok: true, launch_options: 'T %command%' }).args[0], 2);
  await settle();
  assert.equal(h.respond('enable_game', { ok: false, error: 'not ours' }).args[0], 4);
  await settle();
  assert.ok(!h.pending('enable_game'), 'anti-cheat and already-enabled games are skipped');
  assert.equal(h.toasts.at(-1).body, 'FSR4 turned on in 1 game. 1 game could not be changed; see the messages above.');
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

  console.log('Panel verified: instant reopen, scan feedback, toggle flow and notifications.');
})().catch(e => { console.error(e); process.exit(1); });
