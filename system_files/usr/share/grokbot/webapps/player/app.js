// Media player: plays files the user picks (they never leave the computer)
// and, with the "mediakeys" permission, takes the keyboard Play/Pause/Next/
// Previous keys through the Grok Bot OS API (media.keys.wait long poll).
(() => {
  "use strict";
  const T = {
    ko: { title: "미디어 플레이어", add: "파일 추가", clear: "목록 비우기", lang: "English",
      hint: "음악이나 동영상 파일을 고르거나 여기에 끌어다 놓으세요. 파일은 이 컴퓨터 밖으로 나가지 않습니다.",
      needkeys: "키보드의 재생/다음 곡 키로 조작하려면 \"미디어 키\" 권한이 필요합니다.", ask: "권한 요청",
      asking: "확인 창에서 선택해 주세요…", denied: "거부되었습니다. 설정 > 권한에서 바꿀 수 있습니다.",
      keyson: "미디어 키 사용 중", keysoff: "미디어 키 꺼짐", keysask: "미디어 키: 매번 확인", nothing: "재생할 파일을 추가하세요",
      prev: "이전", next: "다음", play: "재생", pause: "일시 정지", key: "미디어 키: %s", cant: "이 파일은 재생할 수 없습니다: %s" },
    en: { title: "Media Player", add: "Add files", clear: "Clear list", lang: "한국어",
      hint: "Pick music or video files, or drop them here. Files never leave this computer.",
      needkeys: "To use the keyboard Play / Next keys, this app needs the \"Media keys\" permission.", ask: "Ask for permission",
      asking: "Answer the prompt…", denied: "Denied. You can change it in Settings > Permissions.",
      keyson: "Media keys on", keysoff: "Media keys off", keysask: "Media keys: ask", nothing: "Add a file to play",
      prev: "Previous", next: "Next", play: "Play", pause: "Pause", key: "Media key: %s", cant: "Cannot play this file: %s" }
  };
  let lang = localStorage.getItem("player.lang") || "ko";
  const t = (k, ...a) => { let s = (T[lang] || T.ko)[k] || k; for (const x of a) s = s.replace("%s", x); return s; };
  const $ = (id) => document.getElementById(id);
  const v = $("v");
  const fmt = (s) => { if (!isFinite(s)) return "0:00"; s = Math.floor(s); const m = Math.floor(s / 60), x = s % 60; return (m >= 60 ? Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0"); };

  let rid = 0;
  class ApiError extends Error { constructor(e) { super(e.message); this.code = e.code; } }
  async function rpc(method, params, signal) {
    const r = await fetch("/v1/rpc", { method: "POST", headers: { "Content-Type": "application/json" }, signal,
      body: JSON.stringify({ jsonrpc: "2.0", id: ++rid, method, params: params || {}, "x-client": "Media Player" }) });
    const b = await r.json();
    if (b.error) throw new ApiError(b.error);
    return b.result;
  }

  let list = [], idx = -1;
  function add(files) {
    for (const f of files) if (/^(audio|video)\//.test(f.type) || /\.(mp3|ogg|oga|opus|flac|wav|m4a|aac|mp4|m4v|webm|mkv|mov)$/i.test(f.name)) list.push({ name: f.name, url: URL.createObjectURL(f), video: /^video\//.test(f.type) || /\.(mp4|m4v|webm|mkv|mov)$/i.test(f.name) });
    if (idx < 0 && list.length) load(0, true);
    render();
  }
  function load(i, autoplay) {
    if (!list.length) return;
    idx = (i + list.length) % list.length;
    const it = list[idx];
    v.src = it.url;
    $("nowt").textContent = it.name.replace(/\.[^.]+$/, "");
    $("art").classList.toggle("hidden", it.video);
    if (autoplay) v.play().catch(() => {});
    if ("mediaSession" in navigator) navigator.mediaSession.metadata = new MediaMetadata({ title: $("nowt").textContent });
    render();
  }
  function toggle() { if (idx < 0) return load(0, true); if (v.paused) v.play().catch(() => {}); else v.pause(); }
  function next() { load(idx + 1, true); }
  function prev() { if (v.currentTime > 3) v.currentTime = 0; else load(idx - 1, true); }

  function render() {
    document.documentElement.lang = lang; document.title = (idx >= 0 && !v.paused ? "▶ " + $("nowt").textContent + " · " : "") + t("title");
    document.querySelectorAll("[data-t]").forEach((e) => { e.textContent = t(e.dataset.t); });
    $("lang").textContent = t("lang");
    $("prev").title = t("prev"); $("next").title = t("next");
    $("playi").src = v.paused ? "i-play.svg" : "i-pause.svg"; $("play").title = v.paused ? t("play") : t("pause");
    if (idx < 0) $("nowt").textContent = t("nothing");
    $("art").classList.toggle("spin", !v.paused);
    const ol = $("list"); ol.replaceChildren();
    list.forEach((it, i) => {
      const li = document.createElement("li");
      li.textContent = (it.video ? "🎬 " : "🎵 ") + it.name; li.title = it.name;
      if (i === idx) li.className = "on";
      li.addEventListener("click", () => load(i, true));
      ol.append(li);
    });
    $("hint").classList.toggle("hidden", list.length > 0);
    const p = $("keys");
    p.textContent = keyMode === "allow" ? t("keyson") : keyMode === "ask" ? t("keysask") : t("keysoff");
    p.className = "pill" + (keyMode === "allow" ? " ok" : "");
    $("need").classList.toggle("hidden", keyMode === "allow");
  }

  v.addEventListener("play", render); v.addEventListener("pause", render); v.addEventListener("ended", () => { if (idx < list.length - 1) next(); else render(); });
  v.addEventListener("error", () => { if (idx >= 0) { $("nowt").textContent = t("cant", list[idx].name); } });
  v.addEventListener("timeupdate", () => { $("cur").textContent = fmt(v.currentTime); $("dur").textContent = fmt(v.duration); if (!seeking) $("pos").value = v.duration ? Math.round(1000 * v.currentTime / v.duration) : 0; });
  let seeking = false;
  $("pos").addEventListener("input", () => { seeking = true; });
  $("pos").addEventListener("change", () => { if (v.duration) v.currentTime = v.duration * $("pos").value / 1000; seeking = false; });
  $("vol").value = localStorage.getItem("player.vol") || 80; v.volume = $("vol").value / 100;
  $("vol").addEventListener("input", () => { v.volume = $("vol").value / 100; localStorage.setItem("player.vol", $("vol").value); });
  $("play").addEventListener("click", toggle); $("next").addEventListener("click", next); $("prev").addEventListener("click", prev);
  $("pick").addEventListener("change", (e) => { add(e.target.files); e.target.value = ""; });
  $("clear").addEventListener("click", () => { v.pause(); v.removeAttribute("src"); v.load(); list.forEach((x) => URL.revokeObjectURL(x.url)); list = []; idx = -1; $("art").classList.remove("hidden"); render(); });
  $("lang").addEventListener("click", () => { lang = lang === "ko" ? "en" : "ko"; localStorage.setItem("player.lang", lang); render(); });
  document.addEventListener("dragover", (e) => { e.preventDefault(); document.body.classList.add("drop"); });
  document.addEventListener("dragleave", () => document.body.classList.remove("drop"));
  document.addEventListener("drop", (e) => { e.preventDefault(); document.body.classList.remove("drop"); add(e.dataTransfer.files); });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" && e.target.type !== "range") return;
    if (e.key === " ") { e.preventDefault(); toggle(); }
    else if (e.key === "ArrowRight") v.currentTime += 5; else if (e.key === "ArrowLeft") v.currentTime -= 5;
    else if (e.key === "n") next(); else if (e.key === "p") prev();
  });

  // ---- media keys through the OS API ----
  let keyMode = "deny";
  async function modeNow() {
    try { const r = await rpc("api.methods"); keyMode = (r.methods.find((m) => m.name === "media.keys.wait") || {}).mode || "deny"; }
    catch (e) { keyMode = "deny"; }
    render();
  }
  const ACT = { "play-pause": toggle, play: () => v.play().catch(() => {}), pause: () => v.pause(), next, previous: prev, stop: () => { v.pause(); v.currentTime = 0; } };
  async function keyLoop() {
    // only while allowed: an "ask" grant would prompt on every poll
    while (keyMode === "allow") {
      try {
        const r = await rpc("media.keys.wait", { timeout: 25 });
        if (r.key && ACT[r.key]) ACT[r.key]();
      } catch (e) {
        if (e.code === -32001) { await modeNow(); break; }
        await new Promise((res) => setTimeout(res, 3000));
      }
    }
  }
  $("askkeys").addEventListener("click", async () => {
    $("askkeys").disabled = true; $("askmsg").textContent = t("asking");
    try {
      const r = await rpc("permissions.request", { scope: "mediakeys", reason: lang === "ko" ? "키보드 미디어 키로 재생 조작" : "Control playback with the keyboard media keys" });
      $("askmsg").textContent = r.mode === "allow" ? "" : t("denied");
    } catch (e) { $("askmsg").textContent = e.message; }
    $("askkeys").disabled = false;
    await modeNow(); keyLoop();
  });

  (async () => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
    await modeNow(); keyLoop();
  })();
})();
