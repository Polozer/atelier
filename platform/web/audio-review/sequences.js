"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const player = $("sequence-audio");
  let clips = [],
    selected,
    generation = 0;
  function stop() {
    generation++;
    player.pause();
    $("playback-status").textContent = "Stopped";
  }
  function play(clip) {
    const token = ++generation;
    if (selected?.file !== clip.file) player.src = clip.file;
    else if (player.readyState > 0) player.currentTime = 0;
    selected = clip;
    $("playing-title").textContent = clip.label;
    $("playing-description").textContent =
      `${clip.description} · ${clip.seconds}s · ${Math.ceil(clip.bytes / 1024)}KiB`;
    $("repeat").disabled = $("stop").disabled = false;
    $("playback-status").textContent = "Loading selected example…";
    // Native playback stays inside the tap: no batch WAV fetch or decoding.
    player.play().catch(() => {
      if (token === generation)
        $("playback-status").textContent =
          "Tap the player’s Play button to listen. Check media volume if needed.";
    });
  }
  player.addEventListener("playing", () => {
    if (!player.paused && !player.error)
      $("playback-status").textContent = "Playing";
  });
  player.addEventListener("ended", () => {
    if (player.ended)
      $("playback-status").textContent = "Finished · Play again to repeat";
  });
  player.addEventListener("error", () => {
    if (player.error)
      $("playback-status").textContent =
        "Could not load this example. Choose another or retry.";
  });
  $("repeat").onclick = () => selected && play(selected);
  $("stop").onclick = stop;
  $("loop").onchange = () => {
    player.loop = $("loop").checked;
  };
  function render() {
    const shown = clips.filter(
      (c) =>
        (!$("activity").value || c.activity === $("activity").value) &&
        (!$("surface").value || c.surface === $("surface").value),
    );
    $("examples").replaceChildren(
      ...shown.map((clip) => {
        const card = document.createElement("article");
        card.className = "card";
        const title = document.createElement("h3");
        title.textContent = clip.label;
        const details = document.createElement("p");
        details.textContent = clip.description;
        const button = document.createElement("button");
        button.textContent = "Play example";
        button.dataset.id = clip.id;
        button.setAttribute("aria-label", `Play ${clip.label}`);
        button.onclick = () => play(clip);
        card.append(title, details, button);
        return card;
      }),
    );
    $("sequence-count").textContent =
      `${shown.length} examples · One short file loads when you play`;
  }
  for (const id of ["activity", "surface"])
    $(id).onchange = () => {
      stop();
      render();
    };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
  });
  window.addEventListener("pagehide", stop);
  fetch("sequences.json", { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error("Example list unavailable");
      return r.json();
    })
    .then((data) => {
      if (
        data.version !== 1 ||
        !Array.isArray(data.clips) ||
        data.clips.length > 80
      )
        throw new Error("Invalid example list");
      clips = data.clips.filter(
        (c) =>
          /^sequences\/[0-9a-f]{64}\/sequence-\d{4}\.m4a$/.test(c.file) &&
          /^(walk|run|roll|slide|landing|transition)$/.test(c.activity) &&
          /^[a-z_]+$/.test(c.surface) &&
          typeof c.label === "string" &&
          typeof c.description === "string" &&
          Number.isFinite(c.seconds) &&
          c.seconds > 0 &&
          c.seconds <= 12 &&
          Number.isInteger(c.bytes) &&
          c.bytes > 0 &&
          c.bytes <= 163840,
      );
      if (!clips.length || clips.length !== data.clips.length)
        throw new Error("Invalid example");
      for (const key of ["activity", "surface"])
        for (const value of [...new Set(clips.map((c) => c[key]))].sort())
          $(key).append(new Option(value.replaceAll("_", " "), value));
      render();
      $("playback-status").textContent = "Ready · Choose an example";
    })
    .catch(() => {
      $("playback-status").textContent =
        "Examples are unavailable. Reload shortly or open the individual-clip library.";
    });
})();
