"use strict";
// Grok Bot OS Settings. Uses only the public OS API (/v1/rpc on this
// origin) with this origin's own grants. DOM nodes only (no HTML strings): SSIDs, origins and
// audit text are untrusted and always go in as text nodes.
(function () {
  let lang = localStorage.getItem("lang") === "en" ? "en" : "ko";
  const t = (k, ...a) => { let s = (I18N[lang] && I18N[lang][k]) || I18N.en[k] || k; for (const x of a) s = s.replace("%s", x); return s; };
  let rid = 0;
  const main = document.getElementById("main");

  class ApiError extends Error {
    constructor(e) { super(e.message); this.code = e.code; this.data = e.data || {}; }
  }
  async function rpc(method, params) {
    const r = await fetch("/v1/rpc", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: ++rid, method, params: params || {} })
    });
    const body = await r.json();
    if (body.error) throw new ApiError(body.error);
    return body.result;
  }

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, "");
      else if (v !== false && v != null) el.setAttribute(k, v);
    }
    for (const c of kids.flat()) if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
    return el;
  }
  const card = (title, ...kids) => h("div", { class: "card" }, title ? h("h3", {}, title) : null, ...kids);
  const row = (...kids) => h("div", { class: "row" }, ...kids);
  const head = (k) => [h("h2", {}, t(k + "_title")), h("p", { class: "sub" }, t(k + "_sub"))];

  let toastTimer;
  function toast(msg, bad) {
    const el = document.getElementById("toast");
    el.textContent = msg; el.className = "show" + (bad ? " bad" : "");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => (el.className = ""), 3500);
  }
  function explain(e) {
    if (e instanceof ApiError && e.code === -32001) return e.data.consent ? t("denied_user") : t("denied");
    return t("failed") + ": " + e.message;
  }
  async function act(fn, okMsg) {
    try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
    catch (e) { toast(explain(e), true); throw e; }
  }
  function sw(on, onchange) {
    const b = h("button", { class: "switch" + (on ? " on" : ""), role: "switch", "aria-checked": String(!!on), type: "button" });
    b.addEventListener("click", async () => {
      const next = !b.classList.contains("on");
      try { await onchange(next); b.classList.toggle("on", next); b.setAttribute("aria-checked", String(next)); } catch (_) {}
    });
    return b;
  }
  function slider(value, onset) {
    const s = h("input", { type: "range", min: "0", max: "100", value: String(value) });
    const out = h("span", { class: "pill" }, value + "%");
    s.addEventListener("input", () => (out.textContent = s.value + "%"));
    s.addEventListener("change", () => onset(parseInt(s.value, 10)).catch(() => {}));
    return [s, out];
  }

  // ---------------- pages ----------------
  const pages = {};

  pages.wifi = async () => {
    const [net, wl] = await Promise.all([rpc("network.status"), rpc("network.wifi.list").catch((e) => ({ error: e }))]);
    const status = card(t("wifi_status"), row(h("span", { class: "grow" }, net.online ? t("online") : t("offline")),
      h("span", { class: "dim" }, (net.default_route || {}).interface || "")));
    const list = card(null);
    if (wl.error) list.append(h("p", { class: "dim" }, wl.error.code === -32001 ? t("denied") : t("unavailable") + " (" + wl.error.message + ")"));
    else if (!wl.networks.length) list.append(h("p", { class: "dim" }, t("wifi_none")));
    else for (const n of wl.networks) {
      const pw = h("input", { type: "password", placeholder: t("wifi_password"), autocomplete: "off" });
      const bars = "▂▄▆█".slice(0, Math.max(1, Math.ceil((n.signal || 0) / 25)));
      const right = n.in_use
        ? [h("span", { class: "pill allow" }, t("wifi_connected")),
           h("button", { type: "button", onclick: () => act(() => rpc("network.wifi.disconnect", { device: n.device }), t("saved")).then(render) }, t("wifi_disconnect"))]
        : [n.security ? pw : h("span", { class: "dim" }, t("wifi_open")),
           h("button", { class: "primary", type: "button", onclick: async () => {
             const p = { ssid: n.ssid }; if (n.security && pw.value) p.password = pw.value;
             toast(t("wifi_connecting"));
             await act(() => rpc("network.wifi.connect", p), t("wifi_connected")).catch(() => {});
             pw.value = ""; render();
           } }, t("wifi_connect"))];
      list.append(row(h("span", { class: "bars" }, bars), h("span", { class: "grow" }, n.ssid,
        h("div", { class: "dim" }, (n.security || t("wifi_open")) + " · " + (n.signal ?? "?") + "%")), ...right));
    }
    const rescan = h("button", { type: "button", onclick: async () => { await rpc("network.wifi.list", { rescan: true }).catch(() => {}); render(); } }, t("wifi_rescan"));
    return [...head("wifi"), status, h("div", { class: "filters" }, rescan), list];
  };

  pages.sound = async () => {
    const a = await rpc("audio.status");
    if (!a.available) return [...head("sound"), card(null, h("p", { class: "dim" }, t("unavailable")))];
    const block = (label, target, v) => {
      const [s, out] = slider(v.volume_percent, (p) => act(() => rpc("audio.set", { target, volume_percent: p })));
      return card(label, row(h("div", { class: "grow" }, s), out),
        row(h("span", { class: "grow" }, t("mute")), sw(v.muted, (m) => act(() => rpc("audio.set", { target, muted: m })))));
    };
    const out = [...head("sound"), block(t("sound_output"), "output", a.output)];
    if (a.input) out.push(block(t("sound_input"), "input", a.input));
    return out;
  };

  // Screens: scale and arrangement (sway outputs) + backlight. A layout change
  // reverts by itself after 15 s unless kept, in case the screen became unusable.
  const SCALES = [1, 1.25, 1.5, 1.75, 2, 2.5, 3];
  let pendingRevert = null;
  const applyDisplay = async (params, before) => {
    await act(() => rpc("display.set", params));
    if (before) {
      clearTimeout(pendingRevert && pendingRevert.timer);
      pendingRevert = { before, until: Date.now() + 15000,
        timer: setTimeout(() => revertDisplay(), 15000) };
    }
    render();
  };
  const revertDisplay = async () => {
    const p = pendingRevert; pendingRevert = null;
    if (!p) return;
    clearTimeout(p.timer);
    try { await rpc("display.set", p.before); toast(t("disp_reverted")); } catch (e) { toast(explain(e), true); }
    render();
  };
  const keepDisplay = () => { if (!pendingRevert) return; if (pendingRevert) clearTimeout(pendingRevert.timer); pendingRevert = null; render(); };
  const arrangement = (o, ref) => {
    if (!ref || o.name === ref.name) return "primary";
    if (o.x >= ref.x + ref.width) return "right";
    if (o.x + o.width <= ref.x) return "left";
    if (o.y + o.height <= ref.y) return "above";
    return "below";
  };
  const placeAt = (where, o, ref) => ({
    right: { x: ref.x + ref.width, y: ref.y }, left: { x: ref.x - o.width, y: ref.y },
    above: { x: ref.x, y: ref.y - o.height }, below: { x: ref.x, y: ref.y + ref.height } }[where]);
  const layoutMap = (outs) => {
    const act_ = outs.filter((o) => o.active);
    if (act_.length < 2) return null;
    const minX = Math.min(...act_.map((o) => o.x)), minY = Math.min(...act_.map((o) => o.y));
    const maxX = Math.max(...act_.map((o) => o.x + o.width)), maxY = Math.max(...act_.map((o) => o.y + o.height));
    const k = Math.min(520 / (maxX - minX), 160 / (maxY - minY));
    const box = h("div", { class: "layout", style: "height:" + Math.round((maxY - minY) * k + 4) + "px" });
    act_.forEach((o, i) => box.append(h("div", { class: "screen" + (o.focused ? " focused" : ""),
      style: `left:${Math.round((o.x - minX) * k)}px;top:${Math.round((o.y - minY) * k)}px;width:${Math.round(o.width * k) - 4}px;height:${Math.round(o.height * k) - 4}px` },
      h("b", {}, String(i + 1)), h("span", {}, o.name))));
    return card(t("disp_layout"), box);
  };
  pages.display = async () => {
    const [l, d] = await Promise.all([rpc("display.list").catch(() => null), rpc("display.brightness")]);
    const out = [...head("display")];
    if (pendingRevert) {
      const left = Math.max(0, Math.ceil((pendingRevert.until - Date.now()) / 1000));
      const cd = h("div", { class: "dim", id: "disp-countdown" }, t("disp_revert_in", left));
      out.push(card(null, row(h("span", { class: "grow" }, h("b", {}, t("disp_keep_q")), cd),
        h("button", { type: "button", onclick: revertDisplay }, t("disp_revert")),
        h("button", { type: "button", class: "primary", onclick: keepDisplay, onpointerdown: keepDisplay }, t("disp_keep")))));
      // Update only the countdown text: re-rendering every second would
      // replace the Keep button under the pointer and eat the click.
      const tick = setInterval(() => {
        if (!pendingRevert || !document.body.contains(cd)) return clearInterval(tick);
        cd.textContent = t("disp_revert_in", Math.max(0, Math.ceil((pendingRevert.until - Date.now()) / 1000)));
      }, 1000);
    }
    if (l && l.outputs.length) {
      const outs = [...l.outputs].sort((a, b) => (a.x - b.x) || (a.y - b.y));
      const ref = outs.find((o) => o.active);
      const m = layoutMap(outs); if (m) out.push(m);
      outs.forEach((o, i) => {
        const res = o.mode ? `${o.mode.width}×${o.mode.height} @ ${Math.round(o.mode.refresh)} Hz` : "—";
        const scaleSel = h("select", { "aria-label": t("disp_scale"), disabled: !o.active,
          onchange: (e) => applyDisplay({ name: o.name, scale: Number(e.target.value) }, { name: o.name, scale: o.scale }) },
          ...SCALES.map((s) => h("option", { value: s, selected: o.scale === s }, Math.round(s * 100) + "%")));
        const rows = [row(h("span", { class: "grow dim" }, [o.make, o.model].filter(Boolean).join(" ") || o.name), h("span", { class: "dim mono" }, res)),
          row(h("span", { class: "grow" }, t("disp_scale")), scaleSel)];
        if (outs.length > 1) {
          const where = arrangement(o, ref);
          if (o !== ref) {
            rows.push(row(h("span", { class: "grow" }, t("disp_position", ref.name)),
              h("select", { "aria-label": t("disp_position", ref.name), disabled: !o.active,
                onchange: (e) => applyDisplay({ name: o.name, ...placeAt(e.target.value, o, ref) }, { name: o.name, x: o.x, y: o.y }) },
                ...["right", "left", "above", "below"].map((w) => h("option", { value: w, selected: where === w }, t("disp_" + w))))));
          }
          rows.push(row(h("span", { class: "grow" }, t("disp_on")),
            sw(o.active, (on) => applyDisplay({ name: o.name, enabled: on }, { name: o.name, enabled: o.active }))));
        }
        out.push(card(t("disp_screen", i + 1) + " · " + o.name + (o.focused ? "  ·  " + t("disp_focused") : ""), ...rows));
      });
    }
    if (!d.available) out.push(card(t("brightness"), h("p", { class: "dim" }, t("no_backlight"))));
    else d.devices.forEach((dev) => {
      const [s, o] = slider(dev.percent, (p) => act(() => rpc("display.set_brightness", { percent: Math.max(1, p) })));
      out.push(card(t("brightness") + " · " + dev.name, row(h("div", { class: "grow" }, s), o)));
    });
    return out;
  };

  pages.notifications = async () => {
    const n = await rpc("notifications.list", { include_history: false });
    const items = card(t("notif_current"));
    if (!n.daemon_running) items.append(h("p", { class: "dim" }, t("notif_daemon_off")));
    else if (!n.notifications.length) items.append(h("p", { class: "dim" }, t("notif_none")));
    else for (const x of n.notifications) items.append(row(h("span", { class: "grow" }, x.summary || "", h("div", { class: "dim" }, x.app || "")), h("span", { class: "pill" }, x.urgency || "")));
    return [...head("notif"),
      card(null, row(h("span", { class: "grow" }, t("dnd"), h("div", { class: "dim" }, t("dnd_hint"))),
        sw(n.dnd, (on) => act(() => rpc("notifications.set_dnd", { enabled: on }), t("saved"))))),
      items];
  };

  pages.lock = async () => {
    const l = await rpc("lock.status");
    const choices = [0, 60, 120, 300, 600, 900, 1800, 3600];
    const sel = (cur, key) => {
      const s = h("select", {}, ...choices.concat(choices.includes(cur) ? [] : [cur]).sort((a, b) => a - b).map((v) =>
        h("option", { value: String(v), selected: v === cur }, v === 0 ? t("never") : v % 60 ? v + t("sec") : v / 60 + t("min"))));
      s.addEventListener("change", () => act(() => rpc("lock.set_idle", { [key]: parseInt(s.value, 10) }), t("saved")).catch(() => {}));
      return s;
    };
    return [...head("lock"),
      card(null, row(h("span", { class: "grow" }, t("screen_off")), sel(l.screen_off_s, "screen_off_s")),
        row(h("span", { class: "grow" }, t("lock_after")), sel(l.lock_s, "lock_s"))),
      card(null, row(h("span", { class: "grow" }, t("pin"), h("div", { class: "dim" }, t("pin_hint"))),
        h("span", { class: "pill " + (l.pin_set ? "allow" : "deny") }, l.pin_set ? t("pin_set") : t("pin_unset"))),
        row(h("span", { class: "grow" }), h("button", { class: "primary", type: "button",
          onclick: () => act(() => rpc("power.action", { action: "lock" })).catch(() => {}) }, t("lock_now"))))];
  };

  pages.keyboard = async () => {
    const i = await rpc("input.status");
    return [...head("kbd"),
      card(null, row(h("span", { class: "grow" }, t("korean_on"), h("div", { class: "dim" }, t("kbd_hint"))),
        i.running ? sw(!!i.active, (on) => act(() => rpc("input.set", { active: on }))) : h("span", { class: "dim" }, t("ime_off")))),
      card(t("ime"), row(h("span", { class: "grow" }, "fcitx5"), h("span", { class: "pill " + (i.running ? "allow" : "deny") }, i.running ? t("ime_running") : t("ime_off"))),
        row(h("span", { class: "grow" }, t("methods")), h("span", { class: "mono" }, (i.input_methods || []).join(", ") || "-")),
        row(h("span", { class: "grow" }, t("triggers")), h("span", { class: "mono" }, (i.trigger_keys || []).join(", ") || "-")))];
  };

  let showAll = false;
  const modePill = (m, has) => has === false ? h("span", { class: "dim" }, "—") : h("span", { class: "pill " + m }, t("mode_" + m));
  pages.permissions = async () => {
    const [p, priv] = await Promise.all([rpc("permissions.list"), rpc("privacy.status").catch(() => ({ sessions: [] }))]);
    const me = location.origin;
    const inuse = card(t("in_use"));
    if (!priv.sessions.length) inuse.append(h("p", { class: "dim" }, t("no_sessions")));
    for (const s of priv.sessions) inuse.append(row(h("span", { class: "pill denyd" }, p.scopes[s.kind] ? (lang === "ko" ? p.scopes[s.kind].ko : p.scopes[s.kind].en) : s.kind),
      h("span", { class: "grow" }, label(s.principal), h("div", { class: "dim" }, s.purpose || "")),
      h("button", { type: "button", onclick: () => act(() => rpc("media.session.stop", { id: s.id })).then(render) }, t("stop"))));
    function label(pr) {
      if (pr.startsWith("local:")) {
        const rest = pr.split(":").slice(2).join(":");
        let n = rest.startsWith("unit=") ? rest.slice(5) : (rest.match(/:script=(?:module:)?(.+)$/) || [])[1] || rest.replace(/^exe=/, "");
        n = n.split("/").pop() || t("perm_unknown");
        if (!rest || rest === "unknown") n = t("perm_unknown");
        return t("perm_local") + ": " + n + (rest && rest !== "unknown" ? " — " + rest : "");
      }
      if (pr === "origin:" + me) return t("perm_this") + " (" + me + ")";
      return pr.replace(/^origin:/, "");
    }
    const cards = p.principals.map((pr) => {
      const tbl = h("table", {}, h("tr", {}, h("th", {}, t("scope")), h("th", {}, t("read")), h("th", {}, t("write")), h("th", {}, t("source")), h("th", {})));
      for (const [s, m] of Object.entries(pr.scopes)) {
        const meta = p.scopes[s];
        if (!showAll && !pr.local && m.read === "deny" && m.write === "deny") continue;
        if (!meta.access.length && !showAll) continue;
        const choose = h("select", { "aria-label": t("set_mode") }, h("option", { value: "" }, t("set_mode") + "…"),
          ...["allow", "ask", "deny"].filter((x) => !(x === "allow" && meta.always_ask)).map((x) => h("option", { value: x }, t("mode_" + x))));
        choose.addEventListener("change", () => { if (choose.value) act(() => rpc("permissions.set", { principal: pr.principal, scope: s, mode: choose.value }), t("saved")).then(render, render); });
        tbl.append(h("tr", {}, h("td", {}, lang === "ko" ? meta.ko : meta.en, meta.always_ask ? h("div", { class: "dim" }, t("always_ask")) : null),
          h("td", {}, modePill(m.read, meta.access.includes("read"))), h("td", {}, modePill(m.write, meta.access.includes("write"))),
          h("td", { class: "dim" }, t("src_" + (m.session ? "session" : m.stored ? "user" : m.source))),
          h("td", {}, choose, " ", m.stored || m.session ? h("button", { type: "button", onclick: () => act(() => rpc("permissions.revoke", { principal: pr.principal, scope: s }), t("saved")).then(render) }, t("revoke")) : null)));
      }
      const anyStored = Object.values(pr.scopes).some((m) => m.stored || m.session);
      return card(null, h("div", { class: "row" }, h("h3", { class: "grow" }, label(pr.principal)),
        h("span", { class: "dim mono" }, pr.principal),
        anyStored ? h("button", { class: "danger", type: "button", onclick: () => act(() => rpc("permissions.revoke", { principal: pr.principal }), t("saved")).then(render) }, t("revoke_all")) : null), tbl);
    });
    return [...head("perm"), h("div", { class: "notice" }, t("perm_notice")), inuse,
      h("div", { class: "filters" }, h("button", { type: "button", onclick: () => { showAll = !showAll; render(); } }, showAll ? t("show_granted") : t("show_all"))),
      ...cards];
  };

  let appsSrc = "";
  // OS updates (bootc). Every action shows the consent prompt (power class).
  const shortDigest = (d) => (d ? d.replace(/^sha256:/, "").slice(0, 12) : "—");
  const when = (s) => (s ? new Date(typeof s === "number" ? s * 1000 : s).toLocaleString(lang === "ko" ? "ko-KR" : "en-US") : "—");
  pages.update = async () => {
    const u = await rpc("update.status");
    const dep = (key, e) => card(t("upd_" + key),
      e ? [row(h("span", { class: "grow mono" }, e.image || "—"), h("span", { class: "pill" + (key === "booted" ? " allow" : "") }, e.version || "—")),
        h("div", { class: "dim mono" }, shortDigest(e.digest) + "  ·  " + when(e.timestamp))]
        : h("p", { class: "dim" }, t("upd_none_" + key)));
    const busy = u.running.filter((a) => a !== "status");
    const refreshSoon = () => { clearTimeout(pages.update.t); pages.update.t = setTimeout(() => { if (location.hash === "#update") render(); }, 4000); };
    // keep polling briefly after starting an action: the root unit may not be "active" yet
    if (busy.length || Date.now() < (pages.update.until || 0)) refreshSoon();
    const start = (method) => act(() => rpc(method), t("upd_started")).then(() => { pages.update.until = Date.now() + 30000; setTimeout(render, 800); }, () => {});
    const btn = (label, method, primary, disabled) => h("button", { type: "button", class: primary ? "primary" : "", disabled: disabled || busy.length > 0,
      onclick: () => start(method) }, t(label));
    const state = busy.length ? t("upd_running_" + busy[0])
      : u.restart_needed ? (u.rollback_queued ? t("upd_restart_rollback") : t("upd_restart_staged"))
      : u.available ? t("upd_available", u.available_version || shortDigest(u.available_digest))
      : u.checked_at ? t("upd_uptodate") : t("upd_never");
    const last = u.last ? h("div", { class: u.last.ok ? "dim" : "err" },
      t("upd_last", t("upd_act_" + u.last.action), when(u.last.finished), u.last.ok ? "OK" : t("failed")) + (u.last.message ? " — " + u.last.message : "")) : null;
    const rb = u.health && u.health.rolled_back;
    const out = [...head("upd")];
    if (rb) out.push(card(null, h("p", { class: "err" }, t("upd_auto_rb", rb.from_version || shortDigest(rb.from), when(rb.at))), h("div", { class: "dim" }, rb.why || "")));
    out.push(card(null,
      row(h("span", { class: "grow" }, h("b", {}, state), h("div", { class: "dim" }, t("upd_checked", when(u.checked_at))), last)),
      row(h("span", { class: "grow" }),
        btn("upd_check", "update.check", !u.available),
        btn("upd_apply", "update.apply", u.available, !u.available),
        u.restart_needed ? h("button", { type: "button", class: "primary", onclick: () => act(() => rpc("power.action", { action: "reboot" })).catch(() => {}) }, t("upd_restart")) : null)));
    out.push(dep("booted", u.booted), dep("staged", u.staged));
    out.push(card(t("upd_rollback"), u.rollback
      ? [row(h("span", { class: "grow mono" }, u.rollback.image || "—"), h("span", { class: "pill" }, u.rollback.version || "—")),
        h("div", { class: "dim mono" }, shortDigest(u.rollback.digest) + "  ·  " + when(u.rollback.timestamp)),
        row(h("span", { class: "grow dim" }, t("upd_rollback_hint")), btn("upd_do_rollback", "update.rollback", false, u.rollback_queued))]
      : h("p", { class: "dim" }, t("upd_none_rollback"))));
    out.push(card(null, h("p", { class: "dim" }, t("upd_health", u.health && u.health.last_good_version || shortDigest(u.health && u.health.last_good)))));
    return out;
  };

  pages.apps = async () => {
    const a = await rpc("apps.list", { include_launchers: false });
    const scopes = await rpc("permissions.list", {}).then((p) => p.scopes).catch(() => ({}));
    const sname = (s) => scopes[s] ? (lang === "ko" ? scopes[s].ko : scopes[s].en) : s;
    const list = card(t("apps_installed"));
    for (const app of a.webapps || []) {
      if (app.id === "settings") continue;
      const icon = app.icon_data ? h("img", { src: app.icon_data, alt: "", width: "36", height: "36", class: "appicon" }) : h("span", { class: "appicon ph" }, "◻");
      const btns = h("span", { class: "btns" },
        h("button", { type: "button", class: "primary", onclick: () => act(() => rpc("apps.launch", { id: app.id }), t("apps_opening")) }, t("apps_open")),
        h("button", { type: "button", onclick: () => { location.hash = "#permissions"; } }, t("apps_perms")),
        app.system ? h("span", { class: "pill" }, t("apps_system")) :
          h("button", { type: "button", class: "danger", onclick: () => act(() => rpc("apps.uninstall", { id: app.id }), t("apps_removed")).then(render, () => {}) }, t("apps_remove")));
      list.append(row(icon, h("span", { class: "grow" },
        h("b", {}, lang === "ko" ? (app.name_ko || app.name) : app.name),
        h("div", { class: "dim mono" }, app.origin + (app.source === "url" ? "" : "  ·  " + t("apps_src_" + app.source))),
        h("div", { class: "dim" }, t("apps_asks") + ": " + ((app.scopes || []).map(sname).join(", ") || t("apps_nothing")))), btns));
    }
    if (!(a.webapps || []).some((x) => x.id !== "settings")) list.append(h("p", { class: "dim" }, t("apps_none")));
    const inp = h("input", { type: "text", placeholder: "https://… / /home/…/my-app.zip", value: appsSrc, "aria-label": t("apps_source"), style: null });
    inp.classList.add("wide");
    inp.addEventListener("input", () => (appsSrc = inp.value));
    const idIn = h("input", { type: "text", placeholder: t("apps_id_ph"), "aria-label": "id" });
    const go = h("button", { type: "button", class: "primary", onclick: async () => {
      const v = inp.value.trim(); if (!v) return;
      const p = /^https?:\/\//.test(v) ? { url: v } : { path: v };
      if (idIn.value.trim()) p.id = idIn.value.trim();
      go.disabled = true; toast(t("apps_installing"));
      try { await act(() => rpc("apps.install", p), t("apps_installed_ok")); appsSrc = ""; render(); } catch (_) {} finally { go.disabled = false; }
    } }, t("apps_install"));
    const add = card(t("apps_add"), h("p", { class: "dim" }, t("apps_add_hint")), row(inp, idIn, go));
    return [...head("apps"), list, add];
  };

  let auditFilter = "", auditWrites = true;
  pages.audit = async () => {
    const params = { limit: 200 }; if (auditFilter) params.decision = auditFilter;
    if (auditWrites) params.access = "write";
    const a = await rpc("audit.list", params);
    const filters = h("div", { class: "filters" }, ...["", "allow", "deny", "error"].map((d) =>
      h("button", { type: "button", class: d === auditFilter ? "primary" : "", onclick: () => { auditFilter = d; render(); } }, d ? t("dec_" + d) : t("all"))),
      h("button", { type: "button", class: auditWrites ? "primary" : "", onclick: () => { auditWrites = !auditWrites; render(); } }, t("writes_only")),
      h("button", { type: "button", onclick: render }, t("refresh")), h("span", { class: "dim" }, a.total + " " + t("entries")));
    const tbl = h("table", {}, h("tr", {}, h("th", {}, t("time")), h("th", {}, t("who")), h("th", {}, t("method")), h("th", {}, t("scope")), h("th", {}, t("decision"))));
    for (const e of a.entries.slice().reverse()) {
      const dec = e.decision || e.event || "-";
      tbl.append(h("tr", {}, h("td", { class: "mono" }, (e.ts || "").replace("T", " ").slice(0, 19)),
        h("td", { class: "mono" }, (e.principal || "").replace(/^origin:/, ""), e.client ? h("div", { class: "dim" }, e.client) : null),
        h("td", { class: "mono" }, e.method || "-", e.params ? h("div", { class: "dim" }, JSON.stringify(e.params)) : null),
        h("td", {}, e.scope || "-"),
        h("td", {}, h("span", { class: "pill " + (dec === "allow" ? "allowd" : dec === "deny" ? "denyd" : "error") }, e.decision ? t("dec_" + dec) : dec),
          e.consent ? h("div", { class: "dim" }, e.consent) : null, e.error ? h("div", { class: "dim" }, e.error) : null)));
    }
    return [...head("audit"), filters, card(null, tbl)];
  };

  // ---------------- shell ----------------
  function applyStatic() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-t]").forEach((el) => (el.textContent = t(el.dataset.t)));
    document.getElementById("lang").textContent = t("lang_other");
    document.title = t("app_title") + " — Grok Bot OS";
  }
  async function render() {
    const page = (location.hash || "#wifi").slice(1);
    const fn = pages[page] || pages.wifi;
    document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
    try {
      const kids = await fn();
      main.replaceChildren(...kids);
    } catch (e) {
      if (!(e instanceof ApiError)) {
        // fetch failed: grokbotd is not answering. Show an offline view and retry.
        main.replaceChildren(h("h2", {}, t("nav_" + page)), card(null,
          h("p", { class: "err" }, t("offline_title")), h("p", { class: "dim" }, t("offline_body")),
          h("button", { type: "button", onclick: render }, t("offline_retry"))));
        clearTimeout(render.retry); render.retry = setTimeout(render, 5000);
        return;
      }
      main.replaceChildren(h("h2", {}, t("nav_" + page)), card(null, h("p", { class: "err" }, explain(e))));
    }
  }
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  document.getElementById("lang").addEventListener("click", () => {
    lang = lang === "ko" ? "en" : "ko"; localStorage.setItem("lang", lang); applyStatic(); render();
  });
  window.addEventListener("hashchange", render);
  applyStatic();
  main.replaceChildren(h("p", { class: "dim" }, t("loading")));
  render();
})();
