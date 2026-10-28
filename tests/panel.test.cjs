// SPDX-License-Identifier: BSD-3-Clause
// The panel's real TSX with controlled hooks, RPC calls and timers (DeckyKit's frontend_harness.cjs).
const test = require('node:test');
const assert = require('node:assert/strict');
const { harness, all, find, findText, settle } = require('./frontend_harness.cjs');

const DLO = '~/.dlo/run %command%';
const TOKEN = 'WINEDLLOVERRIDES=amdxc64=n,b';
const game = { appid: 1817070, name: 'Spider-Man', target_dir: '/g', anticheat: false, enabled: false, verdict: 'unknown', reason: '' };
const gpu890 = { device: 0x150e, family: 150, rev: 20, arch: 'RDNA 3.5', model: 'INT8_LITE', model_name: 'INT8 Lite', verified: true };
const state = (over = {}) => ({
  version: '1.0.0', dll_ready: true, shim_ready: true, gpu: gpu890, error: '',
  recipe: { driver: 'Adrenalin 26.10.1', fsr: '4.1.2', dll_size: 1 }, eula_url: 'https://x',
  download: { state: 'idle', done: 0, total: 1, error: '' }, scanned: true, games: [game],
  settings: { auto_launch_options: true, watermark: false },
  copy_options: { plain: `${TOKEN} %command%`, watermark: `${TOKEN} FSR_WATERMARK=1 %command%` },
  ...over,
});
const ok = (s, extra = {}) => ({ ok: true, state: s, ...extra });

/** The panel with a Steam whose launch options read back what was last set (DLO's by default). */
function panel() {
  const options = {}, applied = [], copied = [], steam = {};
  const h = harness({
    globals: {
      appStore: { GetAppOverviewByAppID: id => ({ 1817070: [2, 22], 2: [2, 28], 4: [2, 22], 5: [2, 1, 36, 38] }[id]
        ? { store_category: { 1817070: [2, 22], 2: [2, 28], 4: [2, 22], 5: [2, 1, 36, 38] }[id] } : null) },
      SteamClient: {
        Apps: {
          RegisterForAppDetails(appid, fn) {
            Promise.resolve().then(() => fn({ strLaunchOptions: options[appid] ?? DLO }));
            return { unregister() {} };
          },
          SetAppLaunchOptions(appid, value) { applied.push([appid, value]); if (!steam.ignoreWrites) options[appid] = value; },
        },
        GameSessions: { RegisterForAppLifetimeNotifications(fn) { steam.lifetime = fn; return { unregister() {} }; } },
      },
      navigator: { clipboard: { writeText: async t => { copied.push(t); } } },
    },
  });
  return Object.assign(h, { applied, copied, steam, options });
}
const pending = (h, name) => h.calls.some(c => c.name === name && !c.settled);
const text = tree => all(tree).flatMap(n => [n.props?.label, typeof n.props?.description === 'string' ? n.props.description : null,
  ...[].concat(n.props?.children ?? []).filter(c => typeof c === 'string')]).filter(Boolean).join(' | ');
const button = (tree, label) => all(tree).find(n => n.type === 'ButtonItem' && [].concat(n.props.children).includes(label));
const toggleOf = (tree, label) => all(tree).find(n => n.type === 'ToggleField' && n.props.label === label);

async function open(h, s = state()) {
  h.render();
  h.respond('get_state', ok(s));
  await settle();
  return h.render();
}

test('opens with a spinner once, then renders the last state at once and refreshes underneath', async () => {
  const h = panel();
  assert.ok(find(h.render(), 'Spinner'));
  h.respond('get_state', ok(state()));
  await settle();
  assert.ok(!pending(h, 'scan_games'), 'the backend already scanned at startup; opening the panel must not rescan');
  assert.match(text(h.render()), /Spider-Man/);
  const tree = h.remount();
  assert.ok(!find(tree, 'Spinner'), 'reopening the panel must not show a spinner');
  assert.match(text(tree), /Spider-Man/);
});

test('a backend that does not answer is a message, never an endless spinner', async () => {
  const h = panel();
  h.render();
  h.fail('get_state');
  await settle();
  assert.equal(find(h.render(), 'Field', 'Backend unavailable').props.children, 'backend gone');
});

test('a backend still scanning says so; Rescan gives feedback', async () => {
  const h = panel();
  await open(h, state({ scanned: false, games: [] }));
  assert.match(text(h.render()), /Scanning your library/);
  h.respond('scan_games', ok(state()));
  await settle();
  button(h.render(), 'Rescan library').props.onClick();
  assert.ok(button(h.render(), 'Scanning…').props.disabled, 'Rescan shows "Scanning…" and is disabled while running');
  h.respond('scan_games', ok(state({ games: [game, { ...game, appid: 2, name: 'E33' }] })));
  await settle();
  assert.equal(button(h.render(), 'Rescan library').props.description, 'Found 2 compatible games.');
});

test('a toggle applies what the backend computed and reports what Steam kept', async () => {
  const h = panel();
  toggleOf(await open(h), 'Spider-Man').props.onChange(true);
  await settle();
  const on = `${TOKEN} ${DLO}`;
  const call = h.respond('enable_game', ok(state({ games: [{ ...game, enabled: true }] }), { launch_options: on }));
  assert.deepEqual(call.args, [1817070, DLO]);
  await settle();
  assert.deepEqual(h.applied, [[1817070, on]]);
  assert.deepEqual(h.respond('launch_options_saved', ok(state({ games: [{ ...game, enabled: true }] }))).args, [1817070, on]);
  await settle();
  assert.ok(toggleOf(h.render(), 'Spider-Man').props.checked, 'the answer carries the new state');
  assert.equal(h.toasts.length, 0);

  // Steam ignores the write: the backend records what Steam has and the user is told
  h.steam.ignoreWrites = true;
  toggleOf(h.render(), 'Spider-Man').props.onChange(false);
  await settle();
  h.respond('disable_game', ok(state(), { launch_options: '-novid', kept: [] }));
  await settle();
  h.respond('launch_options_saved', { ok: true });
  await settle();
  toggleOf(h.render(), 'Spider-Man').props.onChange(true);
  await settle();
  h.respond('enable_game', ok(state(), { launch_options: `${TOKEN} -novid` }));
  await settle();
  assert.deepEqual(h.respond('launch_options_saved', { ok: false, error: 'Steam did not keep the new launch options' }).args[1], on);
  await settle();
  assert.equal(h.toasts.at(-1).body, 'Steam did not keep the new launch options');
});

test('Turn on all skips anti-cheat, online and unknown games; Turn off all restores every game', async () => {
  const h = panel();
  const games = [{ ...game, enabled: true, verdict: 'ok' }, { ...game, appid: 2, name: 'E33' },
    { ...game, appid: 3, name: 'Anti-cheat', anticheat: true }, { ...game, appid: 4, name: 'Hitman' },
    { ...game, appid: 5, name: 'Forza' }, { ...game, appid: 6, name: 'No data' }];
  const tree = await open(h, state({ games }));
  assert.ok(findText(toggleOf(tree, 'Forza'), 'Online multiplayer: skipped by Turn on all'));
  const ac = toggleOf(tree, 'Anti-cheat');
  assert.ok(!ac.props.disabled, 'an anti-cheat game can be turned on by hand');
  assert.ok(all(ac.props.description).some(n => n.props?.style?.color && findText(n, 'Anti-cheat detected')), 'red warning');
  assert.ok(!toggleOf(tree, 'Forza').props.disabled, 'an online game can still be turned on by hand');
  button(tree, 'Turn on FSR4 in all games').props.onClick();
  await settle();
  assert.ok(button(h.render(), 'Turning on… 1/2'), 'progress shows on the button that runs');
  assert.ok(button(h.render(), 'Turn off FSR4 and restore all games').props.disabled);
  assert.equal(h.respond('enable_game', ok(state({ games }), { launch_options: 'T %command%' })).args[0], 2);
  await settle();
  h.respond('launch_options_saved', ok(state({ games })));
  await settle();
  assert.equal(h.respond('enable_game', { ok: false, error: 'not ours', state: state({ games }) }).args[0], 4);
  await settle();
  assert.ok(!pending(h, 'enable_game'), 'anti-cheat, online, unknown and already-enabled games are skipped');
  assert.equal(h.toasts.at(-1).body, 'FSR4 turned on in 1 game. 1 game could not be changed; see the messages above. '
    + 'Skipped as possibly online: 2 games; turn them on by hand if you want.');

  const on = [{ ...game, enabled: true }, { ...game, appid: 2, name: 'E33', enabled: true }];
  h.remount();
  h.respond('get_state', ok(state({ games: on })));
  await settle();
  button(h.render(), 'Turn off FSR4 and restore all games').props.onClick();
  await settle();
  assert.ok(button(h.render(), 'Restoring… 1/2'));
  for (const id of [1817070, 2]) {
    assert.equal(h.respond('disable_game', ok(state(), { launch_options: '-novid', kept: [] })).args[0], id);
    await settle();
    h.respond('launch_options_saved', { ok: true });
    await settle();
  }
  assert.equal(h.toasts.at(-1).body, '2 games restored to how they were.');
});

test('Repair re-checks the library, then sets up every enabled game again', async () => {
  const h = panel();
  const games = [{ ...game, enabled: true }, { ...game, appid: 2, name: 'E33' }];
  button(await open(h, state({ games })), 'Repair FSR4 in all games').props.onClick();
  await settle();
  h.respond('verify_library', ok(state({ games })));
  await settle();
  assert.ok(button(h.render(), 'Repairing… 1/1'), 'repair shows its own progress');
  assert.equal(h.respond('enable_game', ok(state({ games }), { launch_options: DLO })).args[0], 1817070);
  await settle();
  assert.ok(!pending(h, 'enable_game'), 'only games that have FSR4 on are repaired');
  assert.equal(h.toasts.at(-1).body, 'Repaired 1 of 1 game.');
  button(h.render(), 'Repair FSR4 in all games').props.onClick();
  await settle();
  h.respond('verify_library', ok(state({ dll_ready: false, games })));
  await settle();
  assert.ok(!pending(h, 'enable_game'), 'nothing is copied from a damaged library');
  assert.match(h.toasts.at(-1).body, /missing or damaged/);
});

test('launch options: automatic option, the watermark tied to it, copy buttons, Decky Launch Options', async () => {
  const h = panel();
  const games = [{ ...game, enabled: true, managed_options: true }, { ...game, appid: 2, name: 'E33', enabled: true }];
  let tree = await open(h, state({ games }));
  const sw = label => toggleOf(tree, label).props;
  assert.equal(sw('Add launch option automatically').checked, true);
  assert.equal(sw("Show AMD's FSR4 watermark").disabled, false);
  sw("Show AMD's FSR4 watermark").onChange(true);
  await settle();
  assert.deepEqual(h.respond('set_setting', ok(state({ settings: { auto_launch_options: true, watermark: true }, games }))).args,
    ['watermark', true]);
  await settle();
  const marked = `${TOKEN} FSR_WATERMARK=1 ${DLO}`;
  assert.deepEqual(h.respond('apply_watermark', { ok: true, launch_options: marked }).args, [1817070, DLO]);
  await settle();
  assert.deepEqual(h.respond('launch_options_saved', ok(state({ games }))).args, [1817070, marked]);
  await settle();
  assert.ok(!pending(h, 'apply_watermark'), 'only games whose launch options the plugin manages are changed');
  assert.deepEqual(h.applied, [[1817070, marked]]);
  h.respond('get_state', ok(state({ settings: { auto_launch_options: false, watermark: true } })));
  await settle();
  tree = h.render();
  assert.equal(sw("Show AMD's FSR4 watermark").disabled, true, 'watermark is greyed out without the automatic launch option');
  assert.equal(sw("Show AMD's FSR4 watermark").checked, false);
  button(tree, 'Copy launch options').props.onClick();
  await settle();
  button(tree, 'Copy launch options + watermark').props.onClick();
  await settle();
  assert.deepEqual(h.copied, [`${TOKEN} %command%`, `${TOKEN} FSR_WATERMARK=1 %command%`]);
  assert.match(h.toasts.at(-1).body, /^Copied: /);
  sw('Add launch option automatically').onChange(true);
  await settle();
  h.respond('set_setting', { ok: false, error: 'The setting could not be saved (No space left on device).', state: state() });
  await settle();
  assert.match(h.toasts.at(-1).body, /could not be saved/);

  assert.ok(!button(tree, 'Add to Decky Launch Options'));
  h.window.hasDeckyLaunchOptions = true;
  button(h.render(), 'Add to Decky Launch Options').props.onClick();
  assert.equal(h.events.at(-1).type, 'dlo-add-launch-options');
  assert.deepEqual(h.events.at(-1).detail.map(o => [o.id, o.group, o.name, o.on, o.off, o.enableGlobally]), [
    ['fsr4-injector', 'FSR4 Injector', 'FSR4 Injector', TOKEN, '', false],
    ['fsr4-injector-watermark', 'FSR4 Injector', 'AMD FSR4 watermark', 'FSR_WATERMARK=1', '', false],
  ]);
});

test('the AMD download polls only its progress and says why it failed', async () => {
  const h = panel();
  button(await open(h, state({ dll_ready: false })), 'Accept and download').props.onClick();
  await settle();
  assert.match(text(h.render()), /Downloading from AMD/);
  const polls = h.calls.length;
  h.advance(500);
  await settle();
  assert.ok(pending(h, 'download_progress'));
  assert.equal(h.calls.slice(polls).filter(c => c.name === 'get_state').length, 0, 'no full state while it runs');
  h.respond('download_progress', { ok: true, download: { state: 'running', done: 20 * 2 ** 20, total: 43 * 2 ** 20, error: '' }, dll_ready: false });
  await settle();
  assert.equal(find(h.render(), 'Field', 'Downloading from AMD').props.children.join(''), '20 MiB / 43 MiB');
  h.respond('download_dll', { ok: false, error: 'HTTP 503', state: state({ dll_ready: false, download: { state: 'error', done: 0, total: 1, error: 'HTTP 503' } }) });
  await settle();
  assert.deepEqual([h.toasts.at(-1).title, h.toasts.at(-1).body], ['FSR4 download failed', 'HTTP 503']);
  assert.match(text(h.render()), /Last attempt failed \| HTTP 503/);
});

test('a download that ended while the panel was reopened leaves the progress view', async () => {
  const h = panel();
  button(await open(h, state({ dll_ready: false })), 'Accept and download').props.onClick();
  await settle();
  h.remount();
  h.respond('get_state', ok(state({ dll_ready: false, download: { state: 'running', done: 1, total: 2, error: '' } })));
  await settle();
  h.render();
  h.advance(500);
  await settle();
  h.respond('download_progress', { ok: true, download: { state: 'done', done: 2, total: 2, error: '' }, dll_ready: true });
  await settle();
  assert.ok(pending(h, 'get_state'), 'the full state is fetched once the download is over');
  h.respond('get_state', ok(state()));
  await settle();
  assert.equal(find(h.render(), 'Field', 'AMD FSR4 DLL').props.children, 'Ready');
});

test('a damaged manifest is shown and nothing can be turned on', async () => {
  const h = panel();
  const tree = await open(h, state({ error: 'The list of games set up is damaged, so no game can be changed.' }));
  assert.ok(findText(find(tree, 'Field', 'Games cannot be changed'), 'is damaged'));
  assert.ok(toggleOf(tree, 'Spider-Man').props.disabled);
  assert.ok(!button(tree, 'Turn on FSR4 in all games'));
});

test('updates: check, download the verified ZIP, and show why not', async () => {
  const h = panel();
  const tree = await open(h);
  assert.match(text(tree), /FSR4 Injector · v1\.0\.0/);
  button(tree, 'Check for updates').props.onClick();
  await settle();
  assert.ok(button(h.render(), 'Checking…').props.disabled);
  h.respond('check_for_updates', { ok: true, current_version: '1.0.0', latest_version: '1.1.0', update_available: true, download_available: true });
  await settle();
  button(h.render(), 'Download v1.1.0').props.onClick();
  await settle();
  assert.deepEqual(h.respond('perform_update', { ok: true, path: '/home/deck/Downloads/FSR4Injector-1.1.0.zip', version: '1.1.0' }).args, ['1.1.0']);
  await settle();
  assert.match(text(h.render()), /Update downloaded/);
  button(h.render(), 'Check for updates').props.onClick();
  await settle();
  h.respond('check_for_updates', { ok: false, current_version: '1.0.0', update_available: false, error: "GitHub's request limit was reached. Try again later." });
  await settle();
  assert.ok(findText(h.render(), 'request limit'), 'update errors are shown');
  button(h.render(), 'Check for updates').props.onClick();
  await settle();
  h.respond('check_for_updates', { ok: true, current_version: '1.0.0', update_available: false, no_release: true,
    message: 'No release has been published yet (or the repository is private).' });
  await settle();
  assert.ok(findText(h.render(), 'No release has been published yet'));
  assert.ok(!findText(h.render(), 'Up to date'));
});

test('GPU line: verified, beta, and a GPU AMD has no model for', async () => {
  let h = panel();
  let tree = await open(h);
  assert.match(text(tree), /RDNA 3\.5 GPU \| PCI 1002:150e\. AMD's FSR 4\.1\.2 picks its INT8 Lite model here\./);
  assert.doesNotMatch(text(tree), /Beta/);
  h = panel();
  tree = await open(h, state({ gpu: { ...gpu890, device: 0x163f, family: 144, rev: 1, arch: 'RDNA 2 APU (Van Gogh)', verified: false } }));
  assert.match(text(tree), /Beta: not tested on this GPU yet/);
  h = panel();
  tree = await open(h, state({ gpu: { ...gpu890, device: 0x15bf, family: 148, arch: 'RDNA 3 APU', model: null, model_name: '' } }));
  assert.match(text(tree), /GPU not supported \| AMD's FSR 4 has no model for this GPU \(RDNA 3 APU, PCI 1002:15bf\)/);
  assert.ok(toggleOf(tree, game.name).props.disabled, 'nothing can be turned on without a model');
  assert.ok(!button(tree, 'Turn on FSR4 in all games'));
});

test('plugin load: SteamOS update notice, and a warning when a session ended without FSR4', async () => {
  const h = panel();
  const plugin = h.exports.default();
  assert.equal(plugin.name, 'FSR4 Injector');
  h.respond('startup_notice', { ok: true, message: 'SteamOS was updated (a → b).' });
  await settle();
  assert.equal(h.toasts.at(-1).body, 'SteamOS was updated (a → b).');
  h.steam.lifetime({ unAppID: 1817070, bRunning: true });
  await settle();
  h.respond('session_started', { ok: true, managed: true });
  h.steam.lifetime({ unAppID: 1817070, bRunning: false });
  await settle();
  const ended = h.respond('session_ended', { ok: true, managed: true, verdict: 'failed', reason: 'fell back to FSR3' });
  assert.deepEqual(ended.args, [1817070, DLO]);
  await settle();
  assert.deepEqual([h.toasts.at(-1).title, h.toasts.at(-1).body], ['FSR4 not active', 'fell back to FSR3']);
  h.steam.lifetime({ unAppID: 1817070, bRunning: false });
  await settle();
  h.fail('session_ended');  // a backend restarting: no toast, no unhandled rejection
  await settle();
  assert.equal(h.toasts.length, 2);
});
