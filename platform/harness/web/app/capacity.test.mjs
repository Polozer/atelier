import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {buildSync} from 'esbuild';

// Render the actual component without a browser, server binary or generated asset changes.
const {outputFiles} = buildSync({entryPoints: ['src/ui/Capacity.tsx'], bundle: true, write: false,
  platform: 'node', format: 'cjs', packages: 'external', jsx: 'automatic'});
const loaded = {exports: {}};
new Function('require', 'module', 'exports', outputFiles[0].text)(createRequire(import.meta.url), loaded, loaded.exports);
const {Capacity} = loaded.exports;
const vector = (io_slots = 0) => ({memory_mib: 1024, cpu_millis: 1000, temp_mib: 1024, gpu_mib: 0, io_slots});
const job = (changes = {}) => ({id: 'job', owner: 'builder', purpose: 'City export', state: 'uncertain', charged: true,
  resources: vector(), locks: [], first_ready: 90, sequence: 1, bypasses: 0, retained: 2, witnessed: 1,
  wait_reason: '', ancestry_unknown: false, ...changes});
const snapshot = (changes = {}) => ({epoch: 1, boot_id: 'fixture', mode: 'capacity', cutover: true,
  observed_at: 100, recovering: false, total: vector(), reserve: vector(), charged_resources: vector(),
  charged_count: 0, waiting_count: 0, total_records: 0, returned_records: 0, records: [], truncated: false, ...changes});
function render(value, props = {}) {
  return renderToStaticMarkup(createElement(Capacity, {connected: true, bridge: false, serverTime: 100,
    status: {configuration: 'configured', availability: 'available', fresh: true, snapshot: value}, ...props}));
}

test('zero I/O budgets and per-job zero requests are omitted', () => {
  const html = render(snapshot({records: [job()], charged_count: 1}));
  assert.doesNotMatch(html, /I\/O|0 slots/);
});

test('disk is absent from admission when the broker reports no disk budget', () => {
  const nodisk = () => ({...vector(), temp_mib: 0});
  const html = render(snapshot({total: nodisk(), reserve: nodisk(), charged_resources: nodisk(),
    records: [job({resources: {...vector(), temp_mib: 8192}})]}));
  assert.doesNotMatch(html, /[Tt]emporary disk/);
  // An older broker still enforcing a nonzero disk budget must not be hidden.
  assert.match(render(snapshot()), /Temporary disk/);
});

test('retry-required history is not shown in the active queue', () => {
  const html = render(snapshot({waiting_count: 1, records: [
    job({id: 'old', purpose: 'Old retry', state: 'waiting', charged: false}),
    job({id: 'ready', purpose: 'Current request', state: 'queued', charged: false}),
  ]}));
  assert.match(html, /0 reservations · 1 waiting/);
  assert.match(html, /Current request/);
  assert.doesNotMatch(html, /Old retry|awaiting retry/);
});

test('every nonzero I/O accounting dimension remains visible', () => {
  for (const key of ['total', 'reserve', 'charged_resources']) {
    const html = render(snapshot({[key]: vector(2)}));
    assert.match(html, /I\/O contention budget/);
    assert.match(html, /2 slots/);
  }
  assert.match(render(snapshot({records: [job({resources: vector(3)})]})), /3 I\/O contention budget slots/);
});

test('uncertain recovery names the job and owner and waits for verified exits', () => {
  const html = render(snapshot({recovering: true, records: [job()], charged_count: 1}));
  assert.match(html, /capacity-tag warning">Locked/);
  assert.match(html, /Locked for cleanup: City export \(builder\)/);
  assert.match(html, /capacity-tag warning">locked</);
  assert.doesNotMatch(html, />uncertain<|Process ancestry is uncertain/);
});

test('compatibility recovery and truncated unknown recovery are distinct', () => {
  const html = render(snapshot({recovering: true}));
  assert.match(html, /broker compatibility is verified/);
  assert.doesNotMatch(html, /waiting for verified process exits/);
  assert.match(render(snapshot({recovering: true, truncated: true})), /reservations outside this visible list/);
});

test('open admission still reports resources held by a running job', () => {
  const html = render(snapshot({records: [job({state: 'running'})], charged_count: 1}));
  assert.match(html, /capacity-tag">Open</);
  assert.match(html, /1 reservations · 0 waiting/);
  assert.match(html, /resources and locks are available/);
  assert.match(html, /1.0 GiB reserved/);
});

test('bridge recovery remains a bridge until actual cutover', () => {
  const html = render(snapshot({mode: 'legacy-bridge', cutover: false, recovering: true, records: [job()]}));
  assert.match(html, /capacity-tag warning">Capacity bridge recovery/);
  assert.match(html, /Extra concurrency is not enabled/);
  assert.doesNotMatch(html, /Capacity admission|Legacy mutexes remain sealed/);
});

test('sealed maintenance explicitly reports one guarded job with no full cutover', () => {
  const html = render(snapshot({mode: 'sealed-maintenance', cutover: false}));
  assert.match(html, /capacity-tag">Exclusive maintenance/);
  assert.match(html, /One guarded job at a time/);
  assert.match(html, /Sealed legacy locks remain exclusive/);
  assert.match(html, /full concurrency awaits a verified reboot/);
  assert.doesNotMatch(html, />Capacity admission<|>Capacity bridge<|>Legacy slots</);
});

test('maintenance recovery retains visible owner and reservation evidence', () => {
  const html = render(snapshot({mode: 'sealed-maintenance', cutover: false, recovering: true,
    records: [job()], charged_count: 1}));
  assert.match(html, /capacity-tag warning">Maintenance recovery/);
  assert.match(html, /Locked for cleanup: City export \(builder\)/);
  assert.doesNotMatch(html, />Capacity admission<|>Capacity bridge recovery</);
});

test('stale maintenance observations cannot claim current exclusive admission', () => {
  const html = render(snapshot({mode: 'sealed-maintenance', cutover: false, observed_at: 80}));
  assert.match(html, /capacity-tag warning">Capacity status unavailable/);
  assert.match(html, /These figures are stale/);
  assert.doesNotMatch(html, />Exclusive maintenance</);
});

test('stale, disconnected and missing observations never claim current admission', () => {
  for (const html of [render(snapshot({observed_at: 80})), render(snapshot(), {connected: false}), render(null)]) {
    assert.match(html, /capacity-tag warning">Capacity status unavailable/);
    assert.doesNotMatch(html, />Capacity admission</);
    assert.doesNotMatch(html, /capacity-tag">Open</);
  }
  assert.match(render(snapshot({observed_at: 80})), /These figures are stale/);
  assert.match(render(null), /Capacity availability is unknown/);
});

test('a pressure-refused job stays queued and displays its arithmetic', () => {
  const reason = 'waiting for memory: 17510 MiB available, 18432 MiB required; deficit 922 MiB; sample age 0.1s';
  const html = render(snapshot({waiting_count: 1, records: [job({state: 'queued', charged: false, wait_reason: reason, pressure_expires_at: 101.9})]}));
  assert.match(html, /capacity-tag">queued</);
  assert.doesNotMatch(html, /capacity-tag">ready</);
  assert.match(html, /17510 MiB available, 18432 MiB required; deficit 922 MiB; sample age 0.1s/);
});

test('pressure text expires locally before the next board poll', () => {
  const value = snapshot({waiting_count: 1, records: [job({state: 'queued', charged: false,
    wait_reason: 'advisory offer eligible; 17510 MiB available; sample age 1.9s', pressure_expires_at: 100.1})]});
  assert.match(render(value), /17510 MiB available; sample age 1.9s/);
  const expired = render(value, {serverTime: 100.2});
  assert.match(expired, /memory availability is unknown/);
  assert.doesNotMatch(expired, /17510 MiB available|advisory offer eligible/);
  const missing = render(snapshot({records: [job({state: 'queued', charged: false,
    wait_reason: 'selected advisory offer; 17510 MiB available'})]}));
  assert.match(missing, /memory availability is unknown/);
  assert.doesNotMatch(missing, /17510 MiB available|selected advisory offer/);
});

test('the real component schedules expiry within the remaining tenth of a second', () => {
  const effects = []; let ticks = 0;
  const require = createRequire(import.meta.url);
  const react = require('react');
  const local = {exports: {}};
  new Function('require', 'module', 'exports', outputFiles[0].text)((name) => name === 'react'
    ? {...react, useEffect: (effect) => effects.push(effect), useRef: (value) => ({current: value}),
      useState: () => [0, () => ticks++]} : require(name), local, local.exports);
  local.exports.Capacity({connected: true, bridge: false, serverTime: 100,
    status: {fresh: true, snapshot: snapshot({records: [job({state: 'queued', pressure_expires_at: 100.1})]})}});
  const previous = globalThis.setTimeout; let callback, delay;
  try {
    globalThis.setTimeout = (fn, millis) => { callback = fn; delay = millis; return 1; };
    effects.at(-1)();
  } finally { globalThis.setTimeout = previous; }
  assert.ok(delay > 0 && delay <= 101);
  callback();
  assert.equal(ticks, 1);
});
