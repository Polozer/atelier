const test = require('node:test');
const assert = require('node:assert/strict');
const { MARKER, docsOnly, disposition, updateNotice } = require('./contract-review-notice.cjs');
const SHA = 'a'.repeat(40);
const repo = { owner: 'example', repo: 'platform' };
const user = { login: 'writer', type: 'User' };
const bot = { login: 'github-actions[bot]', type: 'Bot' };
const file = filename => ({ filename });
function fixture(overrides = {}) {
  const calls = [];
  const pr = { state: 'open', draft: false, head: { sha: SHA }, changed_files: 1, ...overrides };
  const files = [file('source.py')];
  const comments = [];
  const github = {
    rest: {
      repos: { getCollaboratorPermissionLevel: async ({ username }) => {
        calls.push(['permission', username]);
        return { data: { permission: username === 'writer' ? 'write' : 'read' } };
      } },
      pulls: { get: async () => ({ data: pr }), listFiles: Symbol('files') },
      issues: {
        listComments: Symbol('comments'),
        createComment: async args => calls.push(['create', args]),
        updateComment: async args => calls.push(['update', args]),
      },
    },
    paginate: async endpoint => endpoint === github.rest.pulls.listFiles ? files : comments,
  };
  return { github, repo, pr, files, comments, calls, context: { repo, payload: { issue: { number: 7 } } } };
}

test('documentation exemptions require a complete list and both sides of renames', () => {
  assert.equal(docsOnly([file('README.md'), file('docs/board.png')], 2), true);
  assert.equal(docsOnly([file('README.md')], 2), false);
  assert.equal(docsOnly([], 0), false);
  for (const filename of ['requirements.txt', 'docs/helper.py', 'docs/example.svg', '.github/workflows/test.yml']) {
    assert.equal(docsOnly([file(filename)], 1), false);
  }
  assert.equal(docsOnly([{ filename: 'docs/example.md', previous_filename: 'source.py' }], 1), false);
});

test('ready code warns; draft and documentation do not', async () => {
  const f = fixture();
  assert.match(await disposition(f), /Warning: paid review has not been requested/);
  f.pr.draft = true;
  assert.match(await disposition(f), /^Draft:/);
  f.pr.draft = false;
  f.files[0] = file('AGENTS.md');
  assert.match(await disposition(f), /^Exempt: documentation-only/);
  assert.deepEqual(f.calls, []);
});

test('only an exact human writer request clears the missing-request warning', async () => {
  const f = fixture();
  for (const [body, author] of [['r? cc', bot], ['r? cc', { ...user, login: 'reader' }], ['r? cc\n', user]]) {
    f.comments.splice(0, Infinity, { body, user: author });
    assert.match(await disposition(f), /Warning:/);
  }
  f.comments[0] = { body: 'r? cc', user };
  assert.match(await disposition(f), /request only, not completion or approval/);
  // One request is a PR-level notice, not a demand to pay again for every push.
  f.pr.head.sha = 'b'.repeat(40);
  assert.match(await disposition(f), /^Paid review requested/);
});

test('trivial declaration needs current full SHA, a reason and writer permission', async () => {
  const f = fixture();
  for (const body of [`cc: exempt ${SHA}`, `cc: exempt ${'b'.repeat(40)}\nFormatting only`,
      'cc: exempt aaaaaaa\nFormatting only']) {
    f.comments.splice(0, Infinity, { body, user });
    assert.match(await disposition(f), /Warning:/);
  }
  f.comments[0] = { body: `cc: exempt ${SHA}\nFormatting only; behavior unchanged.`, user: { ...user, login: 'reader' } };
  assert.match(await disposition(f), /Warning:/);
  f.comments[0].user = user;
  assert.match(await disposition(f), /^Exempt: a writer declared/);
  f.pr.head.sha = 'b'.repeat(40);
  assert.match(await disposition(f), /Warning:/);
});

test('permission lookup failure never silently grants an exemption', async () => {
  const f = fixture();
  f.comments.push({ body: `cc: exempt ${SHA}\nFormatting only`, user });
  f.github.rest.repos.getCollaboratorPermissionLevel = async () => { throw Error('unavailable'); };
  await assert.rejects(disposition(f), /unavailable/);
});

test('one bot notice is updated without overwriting human content or spamming unchanged notices', async () => {
  const f = fixture();
  f.comments.push({ id: 1, user, body: `${MARKER}\nImpersonated notice` });
  await updateNotice(f);
  const created = f.calls.find(([action]) => action === 'create')[1];
  assert.match(created.body, /Warning:/);
  f.calls.length = 0;
  f.comments.push({ id: 2, user: bot, body: created.body });
  await updateNotice(f);
  assert.deepEqual(f.calls, []);
  f.comments.push({ body: 'r? cc', user });
  await updateNotice(f);
  const updated = f.calls.find(([action]) => action === 'update')[1];
  assert.equal(updated.comment_id, 2);
  assert.match(updated.body, /Paid review requested/);
  assert.equal(f.calls.filter(([action]) => action === 'create').length, 0);
});

test('a changed head or closed PR prevents stale publication', async () => {
  const f = fixture();
  let reads = 0;
  f.github.rest.pulls.get = async () => ({ data: ++reads === 1 ? f.pr : { ...f.pr, head: { sha: 'b'.repeat(40) } } });
  await updateNotice(f);
  assert.deepEqual(f.calls, []);
  f.pr.state = 'closed';
  f.github.rest.pulls.get = async () => ({ data: f.pr });
  f.github.paginate = async () => { throw Error('closed PR should not paginate'); };
  await updateNotice(f);
  assert.deepEqual(f.calls, []);
});
