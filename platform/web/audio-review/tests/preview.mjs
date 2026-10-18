// Run against a served, populated review bank: AUDIO_REVIEW_URL=https://... node ...
// Uses the existing platform/web Playwright dependency and the installed Chrome.
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright-core");
import assert from "node:assert/strict";
const base = process.env.AUDIO_REVIEW_URL;
assert(
  base,
  "Set AUDIO_REVIEW_URL to the listening site with prepared samples",
);
const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    window.audioProbe = { starts: 0, stops: 0, active: 0 };
    const NativeContext = window.AudioContext;
    window.AudioContext = class extends NativeContext {
      createBufferSource() {
        const source = super.createBufferSource();
        const start = source.start.bind(source),
          stop = source.stop.bind(source);
        let stopped = false;
        source.start = (...args) => {
          window.audioProbe.starts++;
          window.audioProbe.active++;
          source.addEventListener("ended", () => {
            window.audioProbe.active--;
          });
          return start(...args);
        };
        source.stop = (...args) => {
          if (!stopped) window.audioProbe.stops++;
          stopped = true;
          return stop(...args);
        };
        return source;
      }
    };
  });
  await page.goto(base + "?bank=samples");
  await page.waitForFunction(
    () => !document.getElementById("audition-play").disabled,
  );
  await page.waitForSelector(".card audio");
  const loop = page.locator(".clip-loop input").first();
  await loop.check();
  assert.equal(
    await page
      .locator(".card audio")
      .first()
      .evaluate((a) => a.loop),
    true,
  );
  await loop.uncheck();
  assert.equal(
    await page
      .locator(".card audio")
      .first()
      .evaluate((a) => a.loop),
    false,
  );
  await page.locator("#audition-play").click();
  await page.waitForFunction(() => window.audioProbe.starts >= 3);
  assert.match(await page.locator("#audition-now").innerText(), /Walking/);
  await page.locator("#audition-stop").click();
  await page.waitForFunction(() => window.audioProbe.active === 0);
  const count = await page.evaluate(() => window.audioProbe.starts);
  await page.waitForTimeout(650);
  assert.equal(await page.evaluate(() => window.audioProbe.starts), count);
  // Directly audition one selected prepared contact from its card.
  await page.locator(".clip-audition").first().click();
  await page.waitForFunction((n) => window.audioProbe.starts > n, count);
  assert.notEqual(await page.locator("#audition-variant").inputValue(), "");
  await page.locator("#audition-stop").click();
  await page.waitForFunction(() => window.audioProbe.active === 0);
  // A fixed variation remains the audible contact at a faster cadence.
  const variant = await page
    .locator("#audition-variant option")
    .nth(1)
    .getAttribute("value");
  const label = await page
    .locator("#audition-variant option")
    .nth(1)
    .innerText();
  await page.locator("#audition-variant").selectOption(variant);
  await page.locator("#audition-cadence").fill("240");
  await page.locator("#audition-play").click();
  await page.waitForFunction((n) => window.audioProbe.starts >= n + 4, count);
  assert.equal(await page.locator("#audition-now").innerText(), label);
  await page
    .locator(".card audio")
    .first()
    .evaluate((a) => a.play());
  await page.waitForFunction(() => window.audioProbe.active === 0);
  await page
    .locator(".card audio")
    .first()
    .evaluate((a) => a.pause());
  await page.locator("#audition-mode").selectOption("skate");
  await page.locator("#audition-surface").selectOption("concrete");
  await page.locator("#audition-play").click();
  await page.waitForFunction(
    () => document.getElementById("audition-pulse").textContent === "Rolling",
  );
  await page.locator("#audition-speed").fill("0");
  await page.waitForFunction(
    () =>
      document.getElementById("audition-pulse").textContent === "Stationary",
  );
  await page.locator("#audition-speed").fill("8");
  await page.locator("#audition-slide").check();
  await page.waitForFunction(
    () =>
      document.getElementById("audition-pulse").textContent === "Powerslide",
  );
  await page.locator("#audition-land").click();
  assert.match(await page.locator("#audition-now").innerText(), /Landing/);
  await page.locator("#audition-surface").selectOption("wood");
  await page.waitForFunction(() => window.audioProbe.active === 0);
  // Cancel while a fresh surface is loading: late responses must stay silent.
  await page.route("**/samples/**/*.wav", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 350));
    await route.continue();
  });
  await page.locator("#audition-mode").selectOption("footstep");
  await page.locator("#audition-surface").selectOption("grass");
  const before = await page.evaluate(() => window.audioProbe.starts);
  await page.locator("#audition-play").click();
  await page.locator("#audition-stop").click();
  await page.waitForTimeout(1000);
  assert.equal(await page.evaluate(() => window.audioProbe.starts), before);
  await page.unroute("**/samples/**/*.wav");
  await page.locator("#audition-play").click();
  await page.waitForFunction((n) => window.audioProbe.starts > n, before);
  await page.locator("#bank").selectOption("manifest.json");
  await page.waitForFunction(() => window.audioProbe.active === 0);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.locator("#audition-play").click();
  await page.waitForFunction(() => window.audioProbe.active > 0);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForFunction(() => window.audioProbe.active === 0);
  assert.deepEqual(errors, []);
  console.log(
    "PASS: clip loop toggles, real WAV decode/playback, cadence/variation, stop, individual playback, roll/speed/slide/landing, selection stop, load cancellation, bank stop, mobile width, no JS errors",
  );
} finally {
  await browser.close();
}
