// SPDX-License-Identifier: BSD-3-Clause
// Shared from DeckyKit (shared/tests/frontend_harness.cjs): change it there, then `kit sync`.
// Runs the real TSX in a Node `vm` with controlled hooks, RPC calls, toasts, timers and clock: no React, no jest.
//
// Sources: DeckyLS/FSR4Injector tests/frontend_panel.cjs (vm + transpile, manual RPC answers, keep), LegionGo2Companion
// tests/frontend_harness.cjs (useRef/useMemo, toaster, fake clock, auto answers, strict RPCs, module stubs, props,
// useQuickAccessVisible, Decky events, window, Object.is dependencies, build-time constants), DeckyReshade
// tests/frontend_panel.cjs (hook state per component and key, elements inside descriptions, localStorage,
// CustomEvent and recorded window events), FSR4Injector tests/frontend_panel.cjs (the entry's default export, so
// the plugin's setup - Steam registrations, startup toasts - runs in the test; window changed between renders).
// Guarantees: the component's own source runs (relative .ts/.tsx imports too, transpiled with their real file
// names; `modules` stubs a module by name); nothing runs on a real timer or clock, and timers that keep
// rescheduling themselves fail the test instead of hanging it; every RPC call is recorded with its arguments copied
// out of the sandbox (structured clone: undefined and NaN survive), and an argument that cannot be sent (a function,
// a promise) throws at the call instead of hiding in a rejected promise (DeckyVibranceHDR build-contract); with `strict`, an RPC without an answer in
// `responses` fails the call instead of hanging; hook dependencies compare with Object.is like React's; hook state
// belongs to each function component (its parent, type and key, else its turn among siblings of that type), so
// pages that swap whole components keep their state apart and a new key starts afresh; `all`/`find`/`findText` also
// walk elements passed as a description; an element keeps its key (a section that must keep focus across layouts,
// DeckyVibranceHDR); `localStorage` (in memory) and `CustomEvent` exist, and every
// window.dispatchEvent is recorded in `events`; `exports` are the entry's exports (`exports.default()` runs what
// definePlugin was given) and `window` is the sandbox's window, so a test can change it between renders;
// `writes` counts state setter calls (a late answer to an unmounted or hidden panel must write nothing,
// Ayaneo3Companion); `timers`/`intervals` list every timeout/interval set ({ms, done}), and `tick(ms)` runs only
// the intervals of that period (a page with several pollers, Ayaneo3Companion).
// Deliberately not here: real React rendering (DeckyEQ keeps vitest), unmounting a component that leaves the tree
// (its effects clean up on unmount()/remount()), DOM.
//
//   const { harness, all, find, settle } = require('./frontend_harness.cjs');
//   const h = harness({ ui: { Router }, globals: { appStore }, keep: ['Note'] });
//   h.render(); h.respond('get_state', { ok: true, state }); await settle(); find(h.render(), 'Field', 'Status');
//
// Test files are named tests/*.test.cjs; `node --test "tests/*.test.cjs"` finds them all.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const ts = require(require.resolve('typescript', { paths: [root, __dirname] }));

/** Lets every already settled promise chain run. */
const settle = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };

/**
 * entry: the TSX file; component: the function component it defines (exported for the test);
 * ui: @decky/ui members the test controls (any other member is just its name, enough for an element type);
 * globals: Steam globals (appStore, SteamClient...); keep: components left as elements, not rendered;
 * responses: RPC name -> answer (or function of the arguments) given at once; strict: other RPCs fail;
 * api: extra or replaced @decky/api members (e.g. a toaster that throws); modules: name -> exports for any other
 * import (stubs for files the test does not want to run).
 */
function harness({ entry = 'src/index.tsx', component = 'Content', ui = {}, globals = {}, keep = [],
  responses = {}, strict = false, api = {}, modules = {} } = {}) {
  const slots = new Map(), effects = new Map(), pending = [], calls = [], timers = [], intervals = [], toasts = [];
  const listeners = new Map(), frames = [], events = [], storage = new Map();
  let clock = 0, visible = true, writes = 0;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const slot = () => {
    const f = frames[frames.length - 1];
    if (!f) throw new Error('frontend_harness: a hook ran outside render()');
    return `${f.id}:${f.cursor++}`;
  };
  const hooks = {
    useState(value) { const k = slot(); if (!slots.has(k)) slots.set(k, typeof value === 'function' ? value() : value);
      return [slots.get(k), v => { writes++; slots.set(k, typeof v === 'function' ? v(slots.get(k)) : v); }]; },
    useCallback(fn, deps) { const k = slot(), old = slots.get(k); if (!old || !same(old.deps, deps)) slots.set(k, { fn, deps });
      return slots.get(k).fn; },
    useMemo(fn, deps) { const k = slot(), old = slots.get(k); if (!old || !same(old.deps, deps)) slots.set(k, { value: fn(), deps });
      return slots.get(k).value; },
    useRef(value) { const k = slot(); if (!slots.has(k)) slots.set(k, { current: value }); return slots.get(k); },
    useEffect(fn, deps) { const k = slot(), old = effects.get(k); if (!old || !same(old.deps, deps)) pending.push(() => {
      old?.cleanup?.(); effects.set(k, { deps, cleanup: fn() });
    }); },
  };
  // A function component runs where its element is created, in a frame of its own.
  const enter = (id, run) => {
    frames.push({ id, cursor: 0, children: {} });
    try { return run(); } finally { frames.pop(); }
  };
  const call = (type, props, key) => {
    const parent = frames[frames.length - 1], name = type.name || 'anonymous';
    const turn = parent ? parent.children[name] = (parent.children[name] ?? 0) + 1 : 1;
    return enter(`${parent?.id ?? ''}/${name}#${key == null ? turn : `key=${key}`}`, () => type(props ?? {}));
  };
  const el = (type, props, key) => (typeof type === 'function' && !keep.includes(type.name) ? call(type, props, key)
    : key === undefined ? { type, props } : { type, props, key });
  const jsx = { jsx: el, jsxs: el, Fragment: 'Fragment' };
  const copy = value => structuredClone(value);
  // Arguments are copied out of the sandbox, whose objects have their own Object prototype.
  const callable = name => (...args) => {
    let sent;
    try {
      sent = copy(args);
    } catch (e) {  // e.g. a callable used as a .then() handler gets a value, an event handler gets the event
      throw new Error(`RPC ${name}: an argument cannot be sent to the backend (${e.message})`);
    }
    return answer(name, sent);
  };
  const answer = (name, args) => new Promise((resolve, reject) => {
    const call = { name, args, resolve, reject, settled: false };
    calls.push(call);
    if (name in responses) {
      call.settled = true;
      const answer = responses[name];
      resolve(copy(typeof answer === 'function' ? answer(...call.args) : answer));
    } else if (strict) {
      call.settled = true;
      reject(new Error(`unexpected RPC ${name}`));
    }
  });
  const defaults = { useQuickAccessVisible: () => visible };
  const deckyUi = new Proxy(ui, { get: (o, k) => (k in o ? o[k] : k in defaults ? defaults[k] : k) });
  class FakeDate extends Date {
    constructor(...a) { super(...(a.length ? a : [clock])); }
    static now() { return clock; }
  }
  const context = vm.createContext({
    console, Date: FakeDate, performance: { now: () => clock }, structuredClone,
    // What the build replaces (rollup.config.js), so the source runs as the bundle would.
    process: { env: { NODE_ENV: 'test' } }, __PLUGIN_VERSION__: '0.0.0-test',
    localStorage: { getItem: k => storage.get(String(k)) ?? null, setItem: (k, v) => { storage.set(String(k), String(v)); },
      removeItem: k => { storage.delete(String(k)); } },
    CustomEvent: class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
    dispatchEvent: e => { events.push(copy({ type: e?.type, detail: e?.detail })); return true; },
    ...globals,
    setTimeout: (fn, ms = 0) => { const t = { fn, ms, at: clock + ms, done: false }; timers.push(t); return t; },
    clearTimeout: t => { if (t) t.done = true; },
    setInterval: (fn, ms = 0) => { const t = { fn, ms, at: clock + ms, done: false }; intervals.push(t); return t; },
    clearInterval: t => { if (t) t.done = true; },
  });
  if (!('window' in globals)) vm.runInContext('globalThis.window = globalThis', context);
  const cache = new Map();
  function load(file, extra = '') {
    if (cache.has(file)) return cache.get(file).exports;
    const mod = { exports: {} };
    cache.set(file, mod);
    const output = ts.transpileModule(fs.readFileSync(file, 'utf8') + extra, { fileName: file, compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const require = name => {
      if (name === 'react') return hooks;
      if (name === 'react/jsx-runtime') return jsx;
      if (name in modules) return modules[name];
      if (name === '@decky/api') return { callable, definePlugin: fn => fn, toaster: { toast: t => toasts.push(copy(t)) },
        useQuickAccessVisible: () => visible,  // @decky/api exports it too (Ayaneo3Companion imports it from there)
        addEventListener: (event, fn) => { listeners.set(event, [...(listeners.get(event) ?? []), fn]); return fn; },
        removeEventListener: (event, fn) => listeners.set(event, (listeners.get(event) ?? []).filter(f => f !== fn)),
        ...api };
      if (name === '@decky/ui') return deckyUi;
      if (name === 'react-dom') return { createPortal: node => node };
      if (name.startsWith('.')) {
        const base = path.resolve(path.dirname(file), name);
        const found = ['.ts', '.tsx', '/index.ts', '/index.tsx'].map(s => base + s).find(fs.existsSync);
        if (found) return load(found);
      }
      throw Error(`frontend_harness: no module ${name}`);
    };
    vm.runInContext(`(function (module, exports, require) {${output}\n})`, context)(mod, mod.exports, require);
    return mod.exports;
  }
  const exports = load(path.join(root, entry), `\nexport { ${component} };`);
  const Component = exports[component];
  assert.equal(typeof Component, 'function', `${entry} defines no component ${component}`);
  const render = (props = {}) => {
    frames.length = 0;
    const tree = enter(component, () => Component(props));
    pending.splice(0).forEach(fn => fn());
    return tree;
  };
  const take = name => {
    const call = calls.find(c => c.name === name && !c.settled); assert.ok(call, `pending ${name}`);
    call.settled = true; return call;
  };
  return {
    render, calls, timers, intervals, toasts, events, exports, window: vm.runInContext('window', context),
    get now() { return clock; },
    get writes() { return writes; },
    /** One round of every interval, or with ms only of those set for exactly that period. */
    tick(ms) { intervals.filter(t => !t.done && (ms === undefined || t.ms === ms)).forEach(t => t.fn()); },
    /** A Decky event (decky.emit in the backend) to every listener added through @decky/api. */
    emit(event, ...args) { (listeners.get(event) ?? []).forEach(fn => fn(...args)); },
    hide() { visible = false; }, show() { visible = true; },  // the Quick Access Menu closes / opens
    unmount() { for (const e of effects.values()) e.cleanup?.(); effects.clear(); },  // the menu closes
    remount() { this.unmount(); slots.clear(); return render(); },  // closed and opened again
    respond(name, value) { const call = take(name); call.resolve(value); return call; },
    fail(name, error = new Error('backend gone')) { const call = take(name); call.reject(error); return call; },
    /** Every pending timeout (with maxMs, only those set for at most that long), regardless of the clock. */
    fire(maxMs = Infinity) { timers.filter(t => !t.done && t.ms <= maxMs).forEach(t => { t.done = true; t.fn(); }); },
    /** Move the clock on by ms, running due timeouts and intervals in time order. */
    advance(ms) {
      const end = clock + ms;
      for (let runs = 0; ; runs++) {
        if (runs > 100000) throw new Error('timers keep rescheduling themselves: advance() would never end');
        const due = [...timers, ...intervals].filter(t => !t.done && t.at <= end).sort((a, b) => a.at - b.at)[0];
        if (!due) break;
        clock = due.at;
        if (timers.includes(due)) due.done = true; else due.at += Math.max(due.ms, 1);
        due.fn();
      }
      clock = end;
    },
  };
}

/** Every element of a rendered tree, depth first, also those passed as a description. */
function all(node, out = []) {
  if (Array.isArray(node)) node.forEach(n => all(n, out));
  else if (node && typeof node === 'object') {
    out.push(node);
    all(node.props?.children, out);
    all(node.props?.description, out);
  }
  return out;
}
const find = (tree, type, label) => all(tree).find(n => n.type === type && (label === undefined || n.props.label === label));
/** The first element whose label, description or text children contain text. */
const findText = (tree, text) => all(tree).find(n => [n.props?.label, n.props?.description,
  ...[].concat(n.props?.children ?? [])].some(v => typeof v === 'string' && v.includes(text)));

module.exports = { harness, all, find, findText, settle };
