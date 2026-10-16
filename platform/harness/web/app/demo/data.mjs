// Fictional documentation data only. Never read a real mailbox, session or broker.
export const NOW = Date.UTC(2026, 0, 15, 10, 30) / 1000;
const vector = (memory_mib, cpu_millis, gpu_mib = 0) => ({memory_mib, cpu_millis, gpu_mib, temp_mib: 0, io_slots: 0});
const agent = (name, task, busy) => ({agent: name, cursor: 8, pid: null, heartbeat: NOW,
  checkout: `moon-garden-${name}`, stop: 0, supervised: true, task, task_at: NOW - 120,
  session: busy ? 'busy' : 'idle', session_since: NOW - 120, listening: true, pending: 0,
  delivery_error: false, last_to_me: 0, unread: 0, engaged: busy});
const message = (id, sender, recipient, topic, body, age) => ({id, sender, recipient, topic, body,
  body_html: `<p>${body}</p>`, created: NOW - age, reply_to: null, notify: 0, audience: [recipient],
  attachments: [], acknowledged: true});
export const state = {
  time: NOW, sender: 'operator', csrf: 'documentation-demo', has_more: false, total: 4,
  messages: [
    message(4, 'cedar', 'operator', 'evidence', '<strong>Lantern grove ready.</strong> The new path is in the preview build. Collision checks passed; the lights leave a clear route to the garden gate.', 20),
    message(3, 'iris', 'cedar', 'ack', 'The walking animation is ready for your preview. I kept the original rig, so the new clips work with the existing character.', 75),
    message(2, 'moss', 'operator', 'info', '<strong>Build reuse verified.</strong> Unchanged meshes and textures were copied into the preview checkout. Only the lantern grove needs rebuilding.', 160),
    message(1, 'operator', '*', 'request', 'Let’s make the garden welcoming at dusk: a lantern path, softer walking motion and a small playable preview.', 240),
  ],
  agents: [agent('cedar', 'Building the lantern grove preview', true),
    agent('iris', 'Reviewing the walking animation', true), agent('moss', 'idle', false)],
  tasks: [], schedule: {Holding: '', Waiting: '', Handoffs: '', Log: ''}, log_total: 0,
  inbox: {threads: 0, activity: 0}, holders: {}, legacy_slots: {slots: 1, fitting_enabled: false, fitting_paused: false},
  sessions: [], resources: {fresh: true, cpu: 31, available_gib: 21.8},
  disk: {free_bytes: 320 * 1024**3, total_bytes: 1024**4, measured_at: NOW, scan_seconds: 1,
    scanning: false, paused: false, items: []},
  capacity: {configuration: 'capacity', availability: 'available', checked_at: NOW, fresh: true,
    snapshot: {epoch: 1, boot_id: 'documentation-demo', mode: 'capacity', cutover: true, observed_at: NOW,
      recovering: false, total: vector(32768, 10000, 16384), reserve: vector(4096, 2000),
      charged_resources: vector(4096, 3000), charged_count: 1, waiting_count: 0,
      total_records: 1, returned_records: 1, truncated: false,
      records: [{id: 'demo-lanterns', owner: 'cedar', checkout: 'moon-garden-cedar', purpose: 'Lantern grove meshes',
        phase: 'generate', state: 'running', charged: true, resources: vector(4096, 3000),
        locks: ['checkout:moon-garden-cedar'], first_ready: NOW - 90, sequence: 1, bypasses: 0,
        retained: 1, witnessed: 0, wait_reason: '', measured_memory_mib: 716, measured_at: NOW,
        ancestry_unknown: false}]}}
};
