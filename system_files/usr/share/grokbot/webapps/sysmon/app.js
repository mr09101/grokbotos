// System monitor: a web app that uses only the public Grok Bot OS API
// (/v1/rpc on its own origin) with per-scope grants it asks for itself.
(() => {
  "use strict";
  const T = {
    ko: { title: "시스템 모니터", cpu: "CPU", memory: "메모리", disk: "디스크", battery: "배터리", network: "네트워크",
      audit: "OS API 기록 (최근 200건)", lang: "English", live: "실시간", offline: "오프라인 · 저장된 기록",
      need: "이 정보를 보려면 \"%s\" 권한이 필요합니다.", ask: "권한 요청", denied: "거부됨. 설정 > 권한에서 바꿀 수 있습니다.",
      later: "잠시 뒤 다시 요청할 수 있습니다.", cores: "코어 %s개 · 부하 %s", used: "%s / %s 사용",
      free: "%s 남음", avail: "사용 가능 %s · 스왑 %s", nobat: "배터리 없음 (전원 연결)", ac: "전원 연결됨",
      onbat: "배터리 사용 중", online: "인터넷 연결됨", offline_net: "연결 안 됨", rx: "받기", tx: "보내기",
      allow: "허용", deny: "거부", error: "오류", callers: "많이 부른 곳", lastdeny: "최근 거부",
      history: "저장된 기록 %s개 (이 앱 전용 저장소, 다시 시작해도 유지)", persist: "영구 저장소: %s", yes: "예", no: "아니요",
      local: "이 컴퓨터의 프로그램", none: "없음", asking: "확인 창에서 선택해 주세요…",
      askmode: "\"%s\" 권한이 \"매번 확인\"이라 자동으로 새로 고치지 않습니다. 설정 > 권한에서 \"허용\"으로 바꾸거나:", showonce: "지금 한 번 보기" },
    en: { title: "System Monitor", cpu: "CPU", memory: "Memory", disk: "Disk", battery: "Battery", network: "Network",
      audit: "OS API audit (last 200)", lang: "한국어", live: "Live", offline: "Offline · saved history",
      need: "This needs the \"%s\" permission.", ask: "Ask for permission", denied: "Denied. Change it in Settings > Permissions.",
      later: "You can ask again in a while.", cores: "%s cores · load %s", used: "%s of %s used",
      free: "%s free", avail: "%s available · swap %s", nobat: "No battery (on AC)", ac: "On AC power",
      onbat: "On battery", online: "Online", offline_net: "Offline", rx: "In", tx: "Out",
      allow: "allowed", deny: "denied", error: "error", callers: "Top callers", lastdeny: "Recent denials",
      history: "%s samples saved (this app's own storage, kept across restarts)", persist: "Persistent storage: %s", yes: "yes", no: "no",
      local: "Program on this computer", none: "none", asking: "Answer the prompt…",
      askmode: "\"%s\" is set to ask every time, so this does not refresh by itself. Allow it in Settings > Permissions, or:", showonce: "Show once now" }
  };
  const SCOPE = { system: ["시스템 정보", "System information"], power: ["전원", "Power"], network: ["네트워크", "Network"], audit: ["감사 기록", "Audit log"] };
  let lang = localStorage.getItem("sysmon.lang") || "ko";
  const t = (k, ...a) => { let s = (T[lang] || T.ko)[k] || k; for (const x of a) s = s.replace("%s", x); return s; };
  const $ = (id) => document.getElementById(id);
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") el.className = v; else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
    }
    for (const c of kids.flat()) if (c != null) el.append(c.nodeType ? c : String(c));
    return el;
  }
  const fmtB = (b) => { if (b == null) return "—"; const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return b.toFixed(i ? 1 : 0) + " " + u[i]; };

  let rid = 0;
  class ApiError extends Error { constructor(e) { super(e.message); this.code = e.code; this.data = e.data; } }
  async function rpc(method, params) {
    const r = await fetch("/v1/rpc", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: ++rid, method, params: params || {}, "x-client": "System Monitor" }) });
    const b = await r.json();
    if (b.error) throw new ApiError(b.error);
    return b.result;
  }

  // ---- history in IndexedDB (kept in this app's own browser profile) ----
  let db = null;
  function openDb() {
    return new Promise((res) => {
      const q = indexedDB.open("sysmon", 1);
      q.onupgradeneeded = () => q.result.createObjectStore("samples", { keyPath: "t" });
      q.onsuccess = () => res(q.result); q.onerror = () => res(null);
    });
  }
  function addSample(s) {
    if (!db) return;
    const tx = db.transaction("samples", "readwrite"), st = tx.objectStore("samples");
    st.put(s);
    st.delete(IDBKeyRange.upperBound(Date.now() - 3600 * 1000));
  }
  function loadSamples() {
    return new Promise((res) => {
      if (!db) return res([]);
      const q = db.transaction("samples").objectStore("samples").getAll();
      q.onsuccess = () => res(q.result || []); q.onerror = () => res([]);
    });
  }
  let samples = [];

  function spark(canvas, vals, color) {
    const c = canvas.getContext("2d"), w = canvas.width, hh = canvas.height;
    c.clearRect(0, 0, w, hh);
    c.strokeStyle = "#27272a"; c.beginPath(); c.moveTo(0, hh - 1); c.lineTo(w, hh - 1); c.stroke();
    const v = vals.slice(-150);
    if (v.length < 2) return;
    c.strokeStyle = color; c.lineWidth = 2; c.beginPath();
    v.forEach((x, i) => { const px = (i / (v.length - 1)) * w, py = hh - 2 - (Math.max(0, Math.min(100, x || 0)) / 100) * (hh - 4); i ? c.lineTo(px, py) : c.moveTo(px, py); });
    c.stroke();
  }
  function bar(pct) {
    const cls = pct > 90 ? "bad" : pct > 75 ? "warn" : "", i = h("i", { class: cls });
    i.style.width = Math.round(pct) + "%";  // CSSOM, allowed by the CSP (no inline style attributes)
    return h("div", { class: "bar" }, i);
  }

  // ---- permissions: per scope, asked for by the app itself ----
  const need = {};
  function needCard(el, scope, err) {
    el.dataset.need = "1";
    el.replaceChildren(el.firstElementChild && el.firstElementChild.tagName === "H2" ? el.firstElementChild : h("h2", {}, ""));
    const name = SCOPE[scope][lang === "ko" ? 0 : 1];
    const box = h("div", { class: "need" }, h("div", {}, t("need", name)));
    const msg = h("div", { class: "dim" }, "");
    box.append(h("button", { type: "button", class: "primary", onclick: () => ask(scope, msg) }, t("ask")), msg);
    el.append(box);
  }
  async function ask(scope, msg) {
    msg.textContent = t("asking");
    try {
      const r = await rpc("permissions.request", { scope, reason: lang === "ko" ? "시스템 모니터 화면에 표시" : "Shown in System Monitor" });
      msg.textContent = r.mode === "deny" ? t("denied") : "";
      need[scope] = r.mode === "deny";
      await refreshModes();
      tick(true);
    } catch (e) { msg.textContent = e.code === -32001 && e.data && e.data.retry_after_s ? t("later") : e.message; }
  }
  // Effective mode per method (api.methods needs no grant). Only "allow"
  // methods are polled: an "ask" scope would prompt on every poll.
  let modes = {};
  async function refreshModes() {
    try { const m = await rpc("api.methods"); modes = Object.fromEntries(m.methods.map((x) => [x.name, x.mode])); } catch (e) { /* offline */ }
  }
  function askCard(el, scope, method) {
    el.dataset.need = "1";
    el.replaceChildren(el.firstElementChild && el.firstElementChild.tagName === "H2" ? el.firstElementChild : h("h2", {}, ""));
    el.append(h("div", { class: "need" }, h("div", {}, t("askmode", SCOPE[scope][lang === "ko" ? 0 : 1])),
      h("button", { type: "button", onclick: () => { modes[method] = "allow"; tick(true).finally(refreshModes); } }, t("showonce"))));
  }
  async function guarded(scope, el, fn, method) {
    if (method && modes[method] === "ask") { askCard(el, scope, method); return null; }
    if (method && modes[method] === "deny") { needCard(el, scope); need[scope] = true; return null; }
    try { const r = await fn(); need[scope] = false; return r; }
    catch (e) {
      if (e.code === -32001) { need[scope] = true; needCard(el, scope, e.data && e.data.mode); return null; }
      throw e;
    }
  }

  let lastNet = null, online = true;
  async function resources() {
    const r = await guarded("system", $("c-cpu"), () => rpc("system.resources"), "system.resources");
    if (!r) { needCard($("c-mem"), "system"); needCard($("c-disk"), "system"); return; }
    restore("c-cpu"); restore("c-mem"); restore("c-disk");
    const cpu = r.cpu.percent, mem = r.memory, memPct = mem.total_bytes ? 100 * (1 - mem.available_bytes / mem.total_bytes) : 0;
    if (cpu != null) { const s = { t: Date.now(), cpu, mem: memPct }; samples.push(s); samples = samples.filter((x) => x.t > Date.now() - 3600e3); addSample(s); }
    $("cpu-v").textContent = cpu == null ? "…" : cpu.toFixed(0) + "%";
    $("cpu-d").textContent = t("cores", r.cpus, r.load.map((x) => x.toFixed(2)).join(" "));
    $("mem-v").textContent = memPct.toFixed(0) + "%";
    $("mem-d").textContent = t("used", fmtB(mem.total_bytes - mem.available_bytes), fmtB(mem.total_bytes)) + " · " +
      t("avail", fmtB(mem.available_bytes), mem.swap_total_bytes ? fmtB(mem.swap_total_bytes - mem.swap_free_bytes) + " / " + fmtB(mem.swap_total_bytes) : t("none"));
    spark($("cpu-g"), samples.map((x) => x.cpu), "#3b82f6");
    spark($("mem-g"), samples.map((x) => x.mem), "#22c55e");
    $("disk-v").replaceChildren(...r.disks.map((d) => {
      const pct = d.total_bytes ? 100 * (d.total_bytes - d.free_bytes) / d.total_bytes : 0;
      return h("div", {}, h("div", { class: "kv" }, h("b", {}, d.mount), h("span", {}, t("used", fmtB(d.total_bytes - d.free_bytes), fmtB(d.total_bytes)))), bar(pct));
    }));
    const now = r.time, rx = r.network.reduce((a, n) => a + n.rx_bytes, 0), tx = r.network.reduce((a, n) => a + n.tx_bytes, 0);
    if (lastNet && now > lastNet.t) { lastNet.rate = [(rx - lastNet.rx) / (now - lastNet.t), (tx - lastNet.tx) / (now - lastNet.t)]; }
    lastNet = { t: now, rx, tx, rate: lastNet && lastNet.rate };
  }
  const saved = {};
  function restore(id) { if (saved[id] && $(id).dataset.need !== "0") { $(id).replaceChildren(...saved[id]); $(id).dataset.need = "0"; } }

  async function battery() {
    const p = await guarded("power", $("c-bat"), () => rpc("power.status"), "power.status");
    if (!p) return;
    restore("c-bat");
    const el = $("bat-v");
    if (!p.batteries || !p.batteries.length) { el.replaceChildren(h("div", { class: "big" }, "AC"), h("div", { class: "dim" }, t("nobat"))); return; }
    el.replaceChildren(...p.batteries.map((b) => h("div", {}, h("div", { class: "big" }, (b.capacity_percent ?? "—") + "%"), bar(b.capacity_percent || 0),
      h("div", { class: "dim" }, (b.name || "") + " · " + (p.on_ac ? t("ac") : t("onbat")) + (b.status ? " · " + b.status : "")))));
  }

  async function network() {
    const n = await guarded("network", $("c-net"), () => rpc("network.status"), "network.status");
    if (!n) return;
    restore("c-net");
    const rows = [h("div", { class: "kv" }, h("b", {}, n.online ? t("online") : t("offline_net")),
      h("span", { class: "dim" }, lastNet && lastNet.rate ? "↓ " + fmtB(lastNet.rate[0]) + "/s · ↑ " + fmtB(lastNet.rate[1]) + "/s" : ""))];
    for (const i of n.interfaces.filter((x) => x.name !== "lo")) {
      rows.push(h("div", { class: "kv" }, h("span", {}, (i.wireless ? "📶 " : "🔌 ") + i.name), h("span", { class: "dim" }, [i.state, ...(i.addresses || []).map((a) => a.address || a)].filter(Boolean).join(" · "))));
    }
    $("net-v").replaceChildren(...rows);
  }

  function who(p) {
    if (!p) return "?";
    if (p.startsWith("origin:")) return p.slice(7).replace(/^https?:\/\//, "");
    if (p.startsWith("local:")) { const m = p.match(/(?:unit=|script=(?:module:)?|exe=)([^:]+)$/); return t("local") + ": " + (m ? m[1].split("/").pop() : "?"); }
    return p;
  }
  async function auditSummary() {
    const a = await guarded("audit", $("c-audit"), () => rpc("audit.list", { limit: 200 }), "audit.list");
    if (!a) return;
    restore("c-audit");
    const e = a.entries || [], cnt = { allow: 0, deny: 0, error: 0 }, by = {};
    for (const x of e) { cnt[x.decision] = (cnt[x.decision] || 0) + 1; by[x.principal] = (by[x.principal] || 0) + 1; }
    const top = Object.entries(by).sort((a, b) => b[1] - a[1]).slice(0, 4);
    const denies = e.filter((x) => x.decision === "deny").slice(-3).reverse();
    $("audit-v").replaceChildren(
      h("div", { class: "kv" }, h("span", { class: "pill ok" }, t("allow") + " " + cnt.allow), h("span", { class: "pill bad" }, t("deny") + " " + cnt.deny), h("span", { class: "pill warn" }, t("error") + " " + cnt.error)),
      h("div", { class: "dim" }, t("callers")), ...top.map(([p, n]) => h("div", { class: "kv" }, h("span", {}, who(p)), h("span", { class: "dim" }, n))),
      h("div", { class: "dim" }, t("lastdeny")), ...(denies.length ? denies.map((x) => h("div", { class: "kv" }, h("span", {}, x.method), h("span", { class: "dim" }, who(x.principal) + " · " + (x.ts || "").slice(11, 19)))) : [h("div", { class: "dim" }, t("none"))]));
  }

  function status(ok) {
    online = ok;
    $("status").className = "pill " + (ok ? "ok" : "warn");
    $("status").textContent = ok ? t("live") : t("offline");
    if (!ok) { spark($("cpu-g"), samples.map((x) => x.cpu), "#3b82f6"); spark($("mem-g"), samples.map((x) => x.mem), "#22c55e"); }
  }
  let slow = 0, busy = false;
  async function tick(all) {
    if (busy) return;  // never stack calls behind an open prompt
    busy = true;
    try {
      if (all || slow % 5 === 0) await refreshModes();
      await resources();
      if (all || slow++ % 5 === 0) await Promise.all([battery(), network(), auditSummary()]);
      status(true);
    } catch (e) { status(false); }
    finally { busy = false; }
    foot();
  }
  let persisted = null;
  function foot() { $("foot").textContent = t("history", samples.length) + " · " + t("persist", persisted == null ? "?" : persisted ? t("yes") : t("no")); }

  function applyLang() {
    document.documentElement.lang = lang;
    document.title = t("title");
    for (const el of document.querySelectorAll("[data-t]")) el.textContent = t(el.dataset.t);
    $("lang").textContent = t("lang");
  }
  $("lang").addEventListener("click", () => { lang = lang === "ko" ? "en" : "ko"; localStorage.setItem("sysmon.lang", lang); applyLang(); tick(true); });

  // first run: ask for each scope once, one prompt at a time
  async function firstRun() {
    if (localStorage.getItem("sysmon.asked") === "1") return;
    localStorage.setItem("sysmon.asked", "1");
    for (const s of Object.keys(SCOPE)) {
      try { await rpc("permissions.request", { scope: s, reason: lang === "ko" ? "시스템 모니터 화면에 표시" : "Shown in System Monitor" }); } catch (e) { /* shown per card */ }
    }
  }

  (async () => {
    for (const id of ["c-cpu", "c-mem", "c-disk", "c-bat", "c-net", "c-audit"]) saved[id] = [...$(id).childNodes];
    applyLang();
    db = await openDb();
    samples = (await loadSamples()).sort((a, b) => a.t - b.t);
    if (navigator.storage && navigator.storage.persist) { try { persisted = await navigator.storage.persist(); } catch (e) { persisted = false; } }
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
    status(false);
    await firstRun();
    await rpc("system.resources").catch(() => {});  // CPU needs two samples
    await tick(true);
    setInterval(tick, 2000);
  })();
})();
