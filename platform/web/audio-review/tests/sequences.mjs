// Real native media streaming against an encoded bank. No Web Audio injection.
import { createRequire } from "node:module";
import assert from "node:assert/strict";
const { chromium, webkit } = createRequire(import.meta.url)("playwright-core");
const base = process.env.AUDIO_REVIEW_URL;
assert(base, "Set AUDIO_REVIEW_URL to the sequence review origin");
const engine = process.env.AUDIO_REVIEW_BROWSER || "chromium";
assert(["chromium", "webkit"].includes(engine));
const browser = await (engine === "webkit" ? webkit : chromium).launch({
  headless: true,
  ...(engine === "chromium"
    ? {
        channel: "chrome",
        args: ["--autoplay-policy=document-user-activation-required"],
      }
    : {}),
});
try {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [],
    media = [],
    assets = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (/\.(m4a|wav)(\?|$)/.test(r.url())) media.push(r.url());
  });
  page.on("response", (r) => {
    if (!/\.(m4a|wav)(\?|$)/.test(r.url()) && r.status() === 200)
      assets.push(r);
  });
  await page.addInitScript(() => {
    window.webAudioAttempts = 0;
    window.AudioContext = class {
      constructor() {
        window.webAudioAttempts++;
        throw Error("Unexpected Web Audio");
      }
    };
    window.webkitAudioContext = window.AudioContext;
    window.decodeAttempts = 0;
  });
  await page.goto(base);
  await page.waitForFunction(() =>
    document.getElementById("playback-status").textContent.startsWith("Ready"),
  );
  assert.equal(await page.locator("audio").count(), 1);
  assert.equal(media.length, 0, "No media may download before a choice");
  let initialBytes = 0;
  for (const response of assets) initialBytes += (await response.body()).length;
  assert(
    initialBytes < 100 * 1024,
    `Initial page/index too large:${initialBytes}`,
  );
  console.log(
    `${engine}: phone ready, initial${initialBytes}bytes, zero media requests`,
  );
  const cases = [
    ["walk", "asphalt"],
    ["run", "grass"],
    ["roll", "concrete"],
    ["slide", "wood"],
    ["landing", "metal"],
    ["transition", "stone"],
  ];
  const chosen = new Set();
  for (const [activity, surface] of cases) {
    await page.locator("#activity").selectOption(activity);
    await page.locator("#surface").selectOption(surface);
    await page.locator("#examples button").first().tap();
    await page.waitForFunction(() => {
      const a = document.getElementById("sequence-audio");
      return (
        !a.paused &&
        !a.muted &&
        a.volume > 0 &&
        !a.error &&
        a.currentTime > 0.12
      );
    });
    const state = await page
      .locator("audio")
      .evaluate((a) => ({ src: a.currentSrc, duration: a.duration }));
    assert(
      Math.abs(state.duration - 8) < 0.08,
      "Expected bounded8second example",
    );
    chosen.add(state.src);
    assert(
      media.every((url) => chosen.has(url)),
      "Only selected examples may load",
    );
    await page.waitForFunction(() => {
      const a = document.getElementById("sequence-audio");
      return (
        a.buffered.length &&
        a.buffered.end(a.buffered.length - 1) >= a.duration - 0.05
      );
    });
    const requests = media.length;
    await page.locator("#stop").tap();
    await page.waitForFunction(
      () => document.getElementById("sequence-audio").paused,
    );
    const began = Date.now();
    await page.locator("#repeat").tap();
    await page.waitForFunction(() => {
      const a = document.getElementById("sequence-audio");
      return !a.paused && a.currentTime > 0.1;
    });
    assert(Date.now() - began < 3000, "Buffered repeat must start promptly");
    assert.equal(
      media.length,
      requests,
      "Repeat must reuse buffered/cacheable media",
    );
    console.log(
      `${engine}: native ${activity}/${surface}, duration${state.duration}, repeat without another download`,
    );
    await page.locator("#stop").tap();
  }
  await page.locator("#loop").check();
  assert.equal(await page.locator("audio").evaluate((a) => a.loop), true);
  assert.equal(await page.evaluate(() => window.webAudioAttempts), 0);
  assert(media.every((url) => url.endsWith(".m4a")));
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.locator('a[href="clips.html"]').tap();
  await page.waitForSelector(".card audio");
  assert((await page.locator(".card audio").count()) <= 12);
  await page.locator("#next-page").tap();
  assert.match(await page.locator("#page-number").innerText(), /^2 \/ /);
  assert.deepEqual(errors, []);
  console.log(
    `PASS ${engine}: native phone media, no initial audio/AudioContext/WAV batch, all6 activities, buffered repeat, bounded payload and optional12clip pages`,
  );
} finally {
  await browser.close();
}
