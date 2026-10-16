// Render the real UI with a closed set of fictional responses. All network access is intercepted.
import {readFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve, basename} from 'node:path';
import {chromium} from 'playwright-core';
import {NOW, state} from './data.mjs';

const option = (name) => { const i = process.argv.indexOf(name); return i < 0 ? undefined : process.argv[i + 1]; };
const executablePath = option('--browser');
if (!executablePath) throw new Error('Pass --browser /absolute/path/to/chrome');
const output = resolve(option('--output') || fileURLToPath(new URL('../../../docs/media/', import.meta.url)));
const assets = fileURLToPath(new URL('../../../harness/board_web_assets/', import.meta.url));
const mime = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.webp': 'image/webp', '.webmanifest': 'application/manifest+json'};
await mkdir(output, {recursive: true});
const browser = await chromium.launch({executablePath, headless: true});
try {
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}, deviceScaleFactor: 1,
    colorScheme: 'dark', reducedMotion: 'reduce', timezoneId: 'UTC', serviceWorkers: 'block'});
  await context.addInitScript(({now}) => { Date.now = () => now * 1000; delete Object.getPrototypeOf(navigator).serviceWorker; }, {now: NOW});
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== 'https://harness.example.test') throw new Error('Unexpected external request: ' + url.origin);
    if (url.pathname.startsWith('/api/')) {
      const result = url.pathname === '/api/state' ? state
        : url.pathname === '/api/threads' ? {threads: [], has_more: false, unread: 0}
        : url.pathname === '/api/activity' ? {items: [], has_more: false, unread: 0}
        : {ok: true};
      return route.fulfill({json: result});
    }
    const name = url.pathname === '/' ? 'index.html' : basename(url.pathname);
    if (url.pathname !== '/' && url.pathname !== '/' + name) return route.abort();
    const extension = name.slice(name.lastIndexOf('.'));
    try { await route.fulfill({body: await readFile(resolve(assets, name)), contentType: mime[extension] || 'application/octet-stream'}); }
    catch { await route.fulfill({status: 404, body: ''}); }
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('https://harness.example.test/');
  await page.getByText('Lantern grove ready.', {exact: false}).waitFor();
  await page.screenshot({path: resolve(output, 'board-team.png'), animations: 'disabled'});
  await page.setViewportSize({width: 980, height: 1100});
  await page.locator('#tabbar [data-view="render"]').click();
  await page.locator('.capacity-card').waitFor({state: 'visible'});
  await page.screenshot({path: resolve(output, 'board-capacity.png'), animations: 'disabled'});
  if (errors.length) throw new Error(errors.join('\n'));
  console.log('Captured two mock-only board views in ' + output);
  await context.close();
} finally { await browser.close(); }
