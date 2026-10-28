// House Music Generator UI: a shelf of discs, one per generated song.
const $ = (s) => document.querySelector(s);
const shelf = $("#shelf");
const audio = $("#audio");
let songs = [];
let openId = null;

const NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function hash(str) {
  let h = 2166136261;
  for (const c of str) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return h >>> 0;
}

// ---------- generative disc art ----------
// Muted, poster-like inks. Key picks the base colour (minor keys lean dark), the seed picks a
// contrasting second ink; bpm -> ring count, energy -> density.
const INKS = ["#e8e1cf", "#d9442b", "#1f3d2b", "#f2c14e", "#22305c", "#c9b8e8", "#141413", "#9fb8ad", "#e7a1b0", "#7a2e2a", "#3d5a80", "#d8cbb0"];
const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

function palette(spec, seed) {
  const [root = "A", mode = "minor"] = (spec.key || "").split(" ");
  const k = Math.max(0, NOTES.indexOf(root));
  const pool = mode === "minor" ? INKS.filter((c) => lum(c) < 0.45) : INKS.filter((c) => lum(c) >= 0.45);
  const bg = pool[(k * 7) % pool.length];
  const fgs = INKS.filter((c) => Math.abs(lum(c) - lum(bg)) > 0.35);
  const fg = fgs[seed % fgs.length];
  return { bg, fg, ink: lum(bg) < 0.45 ? "#efece4" : "#141413" };
}

function discSVG(song) {
  const r = song.result;
  const spec = r?.spec || {};
  const seed = hash(song.id);
  const { bg, fg, ink } = palette(spec, seed);
  const bpm = spec.bpm || 124;
  const energy = spec.energy ?? 0.7;
  const style = song.status !== "done" ? "blank" : ["rings", "rays", "type"][seed % 3];
  const title = esc((r?.lyrics?.title || "Pressing…").toUpperCase());
  const sub = esc(`${spec.subgenre || "house"} · ${bpm} BPM · ${spec.key || ""}`.toUpperCase());
  let art = "";

  if (style === "blank") {
    // unprinted disc: silver with grooves
    art += `<rect width="200" height="200" fill="#bdbab2"/>`;
    for (let i = 0; i < 26; i++) art += `<circle cx="100" cy="100" r="${30 + i * 2.6}" fill="none" stroke="#fff" stroke-opacity="${0.08 + (i % 3) * 0.06}" stroke-width=".6"/>`;
  } else if (style === "rings") {
    art += `<rect width="200" height="200" fill="${bg}"/>`;
    const n = Math.round(bpm / 10);
    for (let i = 0; i < n; i++) {
      const rr = 30 + (i / n) * 70;
      art += `<circle cx="100" cy="100" r="${rr}" fill="none" stroke="${fg}" stroke-width="${0.6 + energy * 3 * ((i + seed) % 3 === 0 ? 1 : 0.3)}"/>`;
    }
  } else if (style === "rays") {
    art += `<rect width="200" height="200" fill="${bg}"/>`;
    const n = Math.round(12 + energy * 36);
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + (seed % 100) / 50;
      const x = 100 + Math.cos(a) * 100, y = 100 + Math.sin(a) * 100;
      art += `<line x1="100" y1="100" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${fg}" stroke-width="${i % 4 === 0 ? 3 : 0.8}"/>`;
    }
  } else {
    art += `<rect width="200" height="200" fill="${fg}"/>`;
    art += `<text x="100" y="${70 + (seed % 30)}" text-anchor="middle" font-family="Inter Tight" font-weight="900" font-size="64" letter-spacing="-4" fill="${bg}">${bpm}</text>`;
  }

  // printed text around the rim + title band
  const id = `p${song.id}`;
  return `<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${title}">
    <defs><path id="${id}" d="M100,100 m-86,0 a86,86 0 1,1 172,0 a86,86 0 1,1 -172,0"/></defs>
    ${art}
    <text font-family="JetBrains Mono" font-size="6.2" letter-spacing="1.2" fill="${style === "type" ? bg : ink}" opacity=".85"><textPath href="#${id}">${sub} · ${catalog(song)} · ${sub}</textPath></text>
    ${style === "type" ? `<text x="100" y="150" text-anchor="middle" font-family="Inter Tight" font-weight="800" font-size="11" letter-spacing="-.3" fill="${bg}">${title.slice(0, 26)}</text>` : ""}
    ${style === "rings" || style === "rays" ? `<rect x="38" y="146" width="124" height="17" fill="${bg}"/>
      <text x="100" y="158" text-anchor="middle" font-family="Inter Tight" font-weight="800" font-size="10" letter-spacing="-.3" fill="${ink}">${title.slice(0, 24)}</text>` : ""}
    <circle cx="100" cy="100" r="22" fill="#0b0b0a" fill-opacity=".25"/>
    <circle cx="100" cy="100" r="16" fill="#d8d5cc"/>
    <circle cx="100" cy="100" r="7" fill="#0b0b0a"/>
  </svg>`;
}

function catalog(song) {
  const n = songs.length - songs.findIndex((s) => s.id === song.id);
  return `HMG-${String(n).padStart(3, "0")}`;
}

function refLine(song) {
  const sp = song.result?.reference?.spotify;
  const p = song.result?.reference?.parsed;
  if (sp) return { track: sp.track, artist: sp.artist, year: sp.year };
  if (p?.track) return { track: p.track, artist: p.artist };
  return null;
}

// ---------- shelf ----------
function renderShelf() {
  $("#count").textContent = `${songs.filter((s) => s.status === "done").length} discs`;
  if (!songs.length) {
    shelf.innerHTML = `<div class="empty">No discs yet. Press your first one above.</div>`;
    return;
  }
  shelf.innerHTML = songs.map((s) => {
    const ref = refLine(s);
    const sub = s.status === "done" ? (ref ? `after “${esc(ref.track)}”` : esc(s.result.spec.subgenre))
      : s.status === "failed" ? "failed — click for details" : esc(s.step || s.status) + "…";
    return `<button class="item" data-id="${s.id}" style="--tilt:${(hash(s.id) % 40) - 20}deg">
      <div class="disc ${s.status === "done" ? "" : s.status === "failed" ? "failed" : "pressing"}">${discSVG(s)}</div>
      <div class="meta"><div class="cat mono">${catalog(s)} · ${s.result?.audio_path ? "Path " + s.result.audio_path : s.status}</div>
      <div class="t">${esc(s.result?.title || s.request?.prompt || "Untitled")}</div>
      <div class="s mono">${sub}</div></div>
    </button>`;
  }).join("");
}

shelf.addEventListener("click", (e) => {
  if (shelf.dataset.dragged === "1") return;
  const item = e.target.closest(".item");
  if (item) openDetail(item.dataset.id);
});

// vertical wheel -> horizontal scroll, and click-drag scrolling
shelf.addEventListener("wheel", (e) => {
  if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { shelf.scrollLeft += e.deltaY; e.preventDefault(); }
}, { passive: false });
let drag = null;
shelf.addEventListener("pointerdown", (e) => {
  if (e.pointerType !== "mouse") return;
  drag = { x: e.clientX, left: shelf.scrollLeft, moved: false };
  shelf.dataset.dragged = "0";
});
window.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x;
  if (Math.abs(dx) > 5) { drag.moved = true; shelf.classList.add("dragging"); shelf.dataset.dragged = "1"; }
  shelf.scrollLeft = drag.left - dx;
});
window.addEventListener("pointerup", () => { drag = null; shelf.classList.remove("dragging"); });
shelf.addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight") shelf.scrollBy({ left: 300, behavior: "smooth" });
  if (e.key === "ArrowLeft") shelf.scrollBy({ left: -300, behavior: "smooth" });
});

// ---------- detail ----------
const fmt = (t) => (isFinite(t) ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}` : "0:00");

function openDetail(id) {
  const s = songs.find((x) => x.id === id);
  if (!s) return;
  openId = id;
  $("#spin").innerHTML = `<div class="disc ${s.status === "done" ? "" : s.status === "failed" ? "failed" : "pressing"}">${discSVG(s)}</div>`;
  $("#spin").classList.remove("playing");
  const r = s.result;
  const ref = refLine(s);
  let html = `<div class="cat mono">${catalog(s)} · ${esc(s.status)}${r ? " · Path " + esc(r.audio_path) : ""}</div>
    <h1>${esc(r?.title || s.request?.prompt || "Untitled")}</h1>`;
  if (ref) html += `<div class="ref">After <b>“${esc(ref.track)}”</b>${ref.artist ? " — " + esc(ref.artist) : ""}${ref.year ? ", " + esc(ref.year) : ""}</div>`;

  if (s.status === "failed") html += `<p class="err">${esc(s.error)}</p>`;
  else if (s.status !== "done") html += `<p class="mono">Pressing — ${esc(s.step || s.status)}…</p>`;
  else {
    const sp = r.spec;
    html += `<div class="player">
        <button class="play" id="play" aria-label="Play">▶</button>
        <div class="bar" id="bar"><i id="prog"></i></div>
        <div class="time mono" id="time">0:00 / 0:00</div>
      </div>
      <dl class="credits">
        <dt>Genre</dt><dd>${esc(sp.subgenre)}</dd>
        <dt>Tempo / Key</dt><dd>${sp.bpm} BPM · ${esc(sp.key)}</dd>
        <dt>Mood</dt><dd>${esc(sp.mood)}</dd>
        <dt>Instruments</dt><dd>${esc((sp.instruments || []).join(", "))}</dd>
        ${sp.vocals ? `<dt>Vocal</dt><dd>${esc(sp.vocals.style)}</dd>` : ""}
        <dt>Structure</dt><dd>${sp.structure.map((x) => `${esc(x.section)} ${x.bars}`).join(" · ")}</dd>
        ${r.lyrics?.inspiration ? `<dt>Theme</dt><dd>${esc(r.lyrics.inspiration.text)}</dd>` : ""}
      </dl>
      <div class="lyrics"><em>Hook</em>${esc((r.lyrics.hook || []).join("\n"))}<em>Verse</em>${esc((r.lyrics.verse || []).join("\n"))}</div>
      <div class="links mono">
        <a href="${r.links.audio}" download>Download audio</a>
        ${r.links.midi ? `<a href="${r.links.midi}" download>Download MIDI</a>` : ""}
        <button id="showSpec">Show spec</button>
      </div>
      <pre class="spec" id="spec" hidden>${esc(JSON.stringify(sp, null, 2))}</pre>`;
  }
  $("#info").innerHTML = html;
  $("#detail").hidden = false;
  if (location.hash !== `#${id}`) history.replaceState(null, "", `#${id}`);
  document.body.style.overflow = "hidden";

  if (s.status === "done") {
    if (audio.dataset.id !== id) { audio.pause(); audio.src = r.links.audio; audio.dataset.id = id; }
    $("#play").onclick = () => (audio.paused ? audio.play() : audio.pause());
    $("#bar").onclick = (e) => {
      const b = e.currentTarget.getBoundingClientRect();
      if (audio.duration) audio.currentTime = ((e.clientX - b.left) / b.width) * audio.duration;
    };
    $("#showSpec").onclick = () => { $("#spec").hidden = !$("#spec").hidden; };
    syncPlayer();
  }
}

function closeDetail() {
  $("#detail").hidden = true;
  document.body.style.overflow = "";
  openId = null;
  history.replaceState(null, "", location.pathname);
}
$("#close").onclick = closeDetail;
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openId) closeDetail(); });

function syncPlayer() {
  const mine = openId && audio.dataset.id === openId;
  $("#spin").classList.toggle("playing", mine && !audio.paused);
  const play = $("#play");
  if (!play || !mine) return;
  play.textContent = audio.paused ? "▶" : "❚❚";
  play.setAttribute("aria-label", audio.paused ? "Play" : "Pause");
  $("#prog").style.width = audio.duration ? `${(audio.currentTime / audio.duration) * 100}%` : "0";
  $("#time").textContent = `${fmt(audio.currentTime)} / ${fmt(audio.duration)}`;
}
["play", "pause", "timeupdate", "loadedmetadata", "ended"].forEach((ev) => audio.addEventListener(ev, syncPlayer));

// ---------- data ----------
async function load() {
  songs = await (await fetch("/songs")).json();
  renderShelf();
  if (openId) {
    const s = songs.find((x) => x.id === openId);
    // refresh the open panel only when a pressing disc changes state, so playback isn't interrupted
    if (s && s.status !== "done" ) openDetail(openId);
  }
}

async function poll() {
  const before = JSON.stringify(songs.map((s) => [s.id, s.status, s.step]));
  await load().catch(() => {});
  const after = JSON.stringify(songs.map((s) => [s.id, s.status, s.step]));
  const busy = songs.some((s) => s.status === "queued" || s.status === "running");
  if (before !== after && openId) {
    const s = songs.find((x) => x.id === openId);
    if (s?.status === "done" && audio.dataset.id !== openId) openDetail(openId);
  }
  setTimeout(poll, busy ? 2000 : 10000);
}

async function health() {
  try {
    const h = await (await fetch("/health")).json();
    const el = $("#status");
    el.textContent = h.acestep ? "ACE-Step online — vocals" : "ACE-Step offline — instrumental only";
    el.classList.toggle("on", h.acestep);
  } catch { $("#status").textContent = "API offline"; }
}

$("#press").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector(".go");
  const raw = $("#prompt").value.trim();
  if (!raw) return;
  // The field is the "X" in "make a song like X"
  const prompt = /^make a song like/i.test(raw) ? raw : `make a song like ${raw}`;
  btn.disabled = true;
  try {
    const res = await fetch("/songs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt, theme: $("#theme").value.trim() || null, path: $("#path").value || null }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.status);
    $("#prompt").value = "";
    await load();
    shelf.scrollTo({ left: 0, behavior: "smooth" });
  } catch (err) {
    alert(`Couldn't start: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
});

health();
setInterval(health, 15000);
// /#<id> opens that disc directly
load().then(() => { if (location.hash.length > 1) openDetail(location.hash.slice(1)); }).finally(() => setTimeout(poll, 2000));
