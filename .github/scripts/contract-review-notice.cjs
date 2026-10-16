// @cc [owner:fontanierh,label:security] metadata-only-review-reminder
// The reminder MUST use GitHub metadata only, never PR programs or provider credentials.
// A current-head accepted-review status or writer exemption may suppress a code PR's warning.
// A request notice MUST NOT claim that a paid review completed or approved the code.
const MARKER = '<!-- atelier-paid-review-notice -->';
const WRITERS = new Set(['write', 'maintain', 'admin']);

function documentation(path) {
  // Do not exempt arbitrary .txt (requirements), SVG (scripts), configs or unknown files.
  return /\.(md|rst)$/i.test(path) ||
    (/^docs\//.test(path) && /\.(png|jpe?g|webp|gif)$/i.test(path));
}

function docsOnly(files, changedFiles) {
  return files.length > 0 && files.length === changedFiles && files.every(file =>
    documentation(file.filename) && (!file.previous_filename || documentation(file.previous_filename)));
}

async function disposition({ github, repo, pr, files, comments, statuses = [], reviewHead = null }) {
  if (pr.draft) return 'Draft: request review when the code is ready.';
  if (docsOnly(files, pr.changed_files)) {
    return 'Exempt: documentation-only changes. No paid review request is required.';
  }
  const permissions = new Map();
  async function writer(comment) {
    if (comment.user?.type !== 'User') return false;
    const login = comment.user.login;
    if (!permissions.has(login)) {
      const result = await github.rest.repos.getCollaboratorPermissionLevel({ ...repo, username: login });
      permissions.set(login, WRITERS.has(result.data.permission));
    }
    return permissions.get(login);
  }
  for (const comment of comments) {
    const match = /^cc: exempt ([0-9a-f]{40})\n\S[\s\S]*$/.exec(comment.body || '');
    if (match?.[1] === pr.head.sha && await writer(comment)) {
      return 'Exempt: a writer declared this exact head formatting-only or trivial non-code. ' +
        'The declaration must explain why behavior is unchanged; it expires on the next push.';
    }
  }
  if (reviewHead === pr.head.sha && statuses.some(status => status.context === 'Code contracts / review')) {
    return 'Paid review recorded for this head. This notice records acceptance of the request, not ' +
      'completion or approval. Inspect Code contracts / review and its receipt for the reviewed base/head.';
  }
  return '**Warning: paid review has not been recorded for this head.** When this code PR is ready, a writer must ' +
    'post a new comment containing exactly `r? cc`. Pushes never request a paid review. ' +
    'For formatting-only or trivial non-code changes, a writer may instead post ' +
    '`cc: exempt FULL_HEAD_SHA` followed by a newline and an explanation. ' +
    'Do not use that exemption for behavior changes.';
}

async function updateNotice({ github, context }) {
  const repo = context.repo;
  const issue_number = context.payload.pull_request?.number ?? context.payload.issue.number;
  const { data: pr } = await github.rest.pulls.get({ ...repo, pull_number: issue_number });
  if (pr.state !== 'open') return;
  const files = await github.paginate(github.rest.pulls.listFiles, { ...repo, pull_number: issue_number, per_page: 100 });
  const comments = await github.paginate(github.rest.issues.listComments, { ...repo, issue_number, per_page: 100 });
  const statuses = await github.paginate(github.rest.repos.listCommitStatusesForRef, { ...repo, ref: pr.head.sha, per_page: 100 });
  const decision = await disposition({ github, repo, pr, files, comments, statuses, reviewHead: pr.head.sha });
  // Recheck before publication; an old event must not exempt a newly pushed revision.
  const { data: current } = await github.rest.pulls.get({ ...repo, pull_number: issue_number });
  if (current.state !== 'open' || current.head.sha !== pr.head.sha || current.draft !== pr.draft) return;
  const body = `${MARKER}\n### Paid review\n\n${decision}\n\n` +
    'This is an advisory reminder, not a merge gate. Independent peer review and exact-head Python CI still apply.';
  const existing = comments.find(comment => comment.user?.type === 'Bot' &&
    comment.user.login === 'github-actions[bot]' && comment.body?.startsWith(MARKER));
  if (existing) {
    if (existing.body !== body) {
      await github.rest.issues.updateComment({ ...repo, comment_id: existing.id, body });
    }
  } else {
    await github.rest.issues.createComment({ ...repo, issue_number, body });
  }
}

module.exports = { MARKER, docsOnly, disposition, updateNotice };
