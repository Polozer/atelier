"use strict";
const $ = (id) => document.getElementById(id);
if (new URLSearchParams(location.search).get("bank") === "samples")
  $("bank").value = "prepared.json";
let key = "";
let saved = new Set();
try {
  saved = new Set(JSON.parse(localStorage.getItem(key) || "[]"));
} catch {
  /* Private browsing may disable storage. */
}
let manifest;
let page = 0;
const pageSize = 12;
const loopChoices = new Map();
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
function render() {
  if (!manifest) return;
  const query = $("search").value.toLowerCase();
  const category = $("category").value;
  const matching = manifest.clips.filter(
    (c) =>
      (!category || c.category === category) &&
      (!$("favourites").checked || saved.has(c.id)) &&
      `${c.label} ${c.category} ${c.prompt}`.toLowerCase().includes(query),
  );
  const pages = Math.max(1, Math.ceil(matching.length / pageSize));
  page = Math.min(page, pages - 1);
  const clips = matching.slice(page * pageSize, (page + 1) * pageSize);
  $("previous-page").disabled = page === 0;
  $("next-page").disabled = page + 1 >= pages;
  $("page-number").textContent = `${page + 1} / ${pages}`;
  const root = $("library");
  root.replaceChildren();
  for (const name of [...new Set(clips.map((c) => c.category))]) {
    const group = el("section", undefined, "group");
    const heading = el("div", undefined, "group-heading");
    const subset = clips.filter((c) => c.category === name);
    heading.append(el("h2", name), el("span", `${subset.length} TAKES`));
    group.append(heading);
    const grid = el("div", undefined, "grid");
    for (const clip of subset) {
      const card = el(
        "article",
        undefined,
        `card${saved.has(clip.id) ? " saved" : ""}`,
      );
      const top = el("div", undefined, "card-top");
      const title = el("div");
      title.append(
        el("h3", clip.label),
        el("div", `TAKE ${clip.take} / SEED ${clip.seed}`, "take"),
      );
      const star = el("button", saved.has(clip.id) ? "★" : "☆", "star");
      star.setAttribute(
        "aria-label",
        `Favourite ${clip.label}, take ${clip.take}`,
      );
      star.setAttribute("aria-pressed", String(saved.has(clip.id)));
      star.onclick = () => {
        if (saved.has(clip.id)) saved.delete(clip.id);
        else saved.add(clip.id);
        try {
          localStorage.setItem(key, JSON.stringify([...saved]));
        } catch {
          /* Export still works. */
        }
        star.textContent = saved.has(clip.id) ? "★" : "☆";
        star.setAttribute("aria-pressed", String(saved.has(clip.id)));
        card.classList.toggle("saved", saved.has(clip.id));
        if ($("favourites").checked) render();
      };
      top.append(title, star);
      card.append(top);
      if (
        clip.status === "ready" &&
        /^(audio\/clip|samples\/([0-9a-f]{64}\/)?sample)-\d+\.wav$/.test(
          clip.file,
        )
      ) {
        const audio = el("audio");
        const loopLabel = el("label", undefined, "check clip-loop");
        const loop = el("input");
        loop.type = "checkbox";
        loop.checked = loopChoices.get(clip.file) ?? Boolean(clip.loop);
        loop.onchange = () => {
          audio.loop = loop.checked;
          loopChoices.set(clip.file, loop.checked);
        };
        loopLabel.append(loop, document.createTextNode("Loop playback"));
        audio.controls = true;
        audio.preload = "none";
        audio.src = clip.file;
        audio.loop = loop.checked;
        audio.setAttribute("aria-label", `${clip.label}, take ${clip.take}`);
        audio.onplay = () => {
          document.querySelectorAll("audio").forEach((other) => {
            if (other !== audio) other.pause();
          });
        };
        card.append(audio, loopLabel);
        const bottom = el("div", undefined, "card-bottom");
        const download = el("a", "Download WAV ↓");
        download.href = clip.file;
        download.download = `${clip.category}-${clip.label}-take-${clip.take}.wav`;
        bottom.append(
          el(
            "span",
            `${clip.seconds.toFixed(2)} SEC${clip.loop ? " · LOOP" : ""}`,
          ),
          download,
        );
        card.append(bottom);
      } else
        card.append(
          el(
            "div",
            clip.status === "generating"
              ? "Generating…"
              : clip.status === "failed"
                ? "Generation needs attention"
                : "In the generation queue",
            "waiting",
          ),
        );
      const details = el("details");
      details.append(
        el("summary", "Prompt & provenance"),
        el("p", clip.prompt),
        el(
          "p",
          `${manifest.model} · ${manifest.runtime} · ${manifest.steps} steps · CFG ${manifest.cfg} · ${manifest.dit_dtype}`,
        ),
      );
      if (clip.audio) details.append(el("p", `SHA-256 ${clip.audio.sha256}`));
      if (clip.cue)
        details.append(
          el(
            "p",
            `${clip.cue} · ${clip.trigger} · Source ${clip.source_id} · Candidate pending listening acceptance`,
          ),
        );
      card.append(details);
      grid.append(card);
    }
    group.append(grid);
    root.append(group);
  }
  $("count").textContent =
    `${matching.length} matching · ${saved.size} favourites`;
  $("empty").hidden = matching.length !== 0;
  const ready = manifest.clips.filter((c) => c.status === "ready").length;
  $("progress").textContent =
    `${ready} / ${manifest.clips.length} takes ready${ready === manifest.clips.length ? " · Library complete" : " · Updates automatically"}`;
}
function pauseAll() {
  document.querySelectorAll("audio").forEach((a) => a.pause());
}
for (const id of ["search", "category", "favourites"])
  $(id).addEventListener("input", () => {
    pauseAll();
    page = 0;
    render();
  });
$("previous-page").onclick = () => {
  pauseAll();
  page--;
  render();
};
$("next-page").onclick = () => {
  pauseAll();
  page++;
  render();
};
$("bank").onchange = () => {
  pauseAll();
  page = 0;
  manifest = undefined;
  $("library").replaceChildren();
  $("category").replaceChildren(new Option("All categories", ""));
  key = "";
  try {
    saved = new Set(JSON.parse(localStorage.getItem(key) || "[]"));
  } catch {
    saved = new Set();
  }
  refresh();
};
$("export").onclick = () => {
  if (!manifest) return;
  const data = {
    plan_hash: manifest.plan_hash,
    favourites: manifest.clips.filter((c) => saved.has(c.id)),
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const anchor = el("a");
  anchor.href = url;
  anchor.download = "sound-shortlist.json";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
async function refresh() {
  const selected = $("bank").value;
  try {
    const response = await fetch(selected, { cache: "no-store" });
    if (!response.ok) throw new Error("Manifest unavailable");
    const next = await response.json();
    if (selected !== $("bank").value) return;
    if (manifest && JSON.stringify(next) === JSON.stringify(manifest)) return;
    document.title = next.title;
    const nextKey = `atelier-sfx-shortlist-v1-${next.plan_hash}`;
    if (key !== nextKey) {
      key = nextKey;
      try {
        saved = new Set(JSON.parse(localStorage.getItem(key) || "[]"));
      } catch {
        saved = new Set();
      }
    }
    if (!manifest)
      for (const category of [...new Set(next.clips.map((c) => c.category))]) {
        const option = el("option", category);
        option.value = category;
        $("category").append(option);
      }
    // Avoid replacing a playing audio element during periodic progress checks.
    if (
      !manifest ||
      ![...document.querySelectorAll("audio")].some((a) => !a.paused)
    ) {
      manifest = next;
      render();
    }
  } catch {
    $("progress").textContent =
      $("bank").value === "prepared.json"
        ? "Contact samples are being prepared · Raw takes are available now"
        : "Connection interrupted · Retrying shortly";
  }
}
refresh();
setInterval(refresh, 15000);
