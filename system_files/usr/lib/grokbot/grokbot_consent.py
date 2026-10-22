#!/usr/bin/python3
"""Grok Bot OS consent prompt (GTK3 + layer-shell, overlay layer).

grokbotd runs this when a caller's mode for a scope is "ask". The request
arrives as JSON on stdin; the answer is printed on stdout:
  once | always | deny
Esc, closing, or no answer within the timeout means deny. "always" is
offered only when the request allows it (never for camera, microphone,
power or permission changes). The prompt takes the keyboard exclusively
so nothing else can type into it, and its default button is Deny.

The text building is pure (lines()) so it can be unit-tested without GTK.
"""
import json
import sys
import time

ARM_S = 0.6


def who(req):
    p = req.get("principal") or "?"
    if p.startswith("origin:"):
        ko, en = "웹 앱 %s" % p[7:], "Web app %s" % p[7:]
    elif p.startswith("local:"):
        from grokbotd import peer
        n = peer.describe(p)
        if p.endswith(":unknown") or p.count(":") < 2:
            ko, en = "이 컴퓨터의 알 수 없는 프로그램", "An unidentified program on this computer"
        else:
            ko, en = "이 컴퓨터의 프로그램: %s" % n, "Program on this computer: %s" % n
        detail = p.split(":", 2)[2] if p.count(":") >= 2 else ""
        if detail and detail != n:
            ko += " (%s)" % detail
            en += " (%s)" % detail
    else:
        ko = en = p
    c = req.get("client")
    if c:
        ko += " · 스스로 밝힌 이름: %s" % c
        en += " · says it is: %s" % c
    return ko, en


def action(req):
    t = req.get("description") or [req.get("method"), req.get("method")]
    if isinstance(t, str):
        t = [t, t]
    params = req.get("summary") or {}
    detail = ", ".join("%s=%s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in sorted(params.items()))
    return t[0], t[1], "%s(%s)" % (req.get("method"), detail)


def lines(req):
    wk, we = who(req)
    ak, ae, call = action(req)
    return {
        "title": "권한 요청 / Permission request",
        "who": (wk, we),
        "scope": (req.get("scope_ko") or req.get("scope"), req.get("scope_en") or req.get("scope")),
        "action": (ak, ae),
        "call": call,
        "always": bool(req.get("allow_always")),
        "session": bool(req.get("allow_session")),
        "once": req.get("allow_once", True) is not False,
        "warning": req.get("warning"),
        "sensitive": req.get("scope") in ("camera", "microphone", "power", "permissions"),
    }


CSS = b"""
window.grokbot-consent { background-color: rgba(0,0,0,0); }
.card { background-color: #18181b; border: 2px solid #f59e0b; border-radius: 16px; padding: 22px; color: #f4f4f5; }
.card.sensitive { border-color: #ef4444; }
.title { font-size: 20px; font-weight: bold; }
.key { color: #a1a1aa; font-size: 12px; }
.val { font-size: 15px; }
.en { color: #a1a1aa; font-size: 12px; }
.call { font-family: monospace; font-size: 11px; color: #71717a; }
button { padding: 8px 14px; border-radius: 10px; }
button.deny { background: #3f3f46; color: #fff; }
button.allow { background: #2563eb; color: #fff; }
button.always { background: #1d4ed8; color: #fff; }
.timer { color: #a1a1aa; font-size: 12px; }
button.session { background: #1e40af; color: #fff; }
/* Keyboard focus must be obvious: Tab moves between Deny / Allow buttons. */
button { border: 3px solid transparent; outline: none; }
button:focus { border-color: #fbbf24; box-shadow: 0 0 0 3px rgba(251,191,36,0.45); }
.warn { color: #fbbf24; font-size: 14px; font-weight: bold; }
.warn-en { color: #fbbf24; font-size: 12px; }
"""


def main():
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print("deny")
        return 0
    t = lines(req)
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GLib, Gdk, Gtk, GtkLayerShell

    answer = {"v": "deny"}
    win = Gtk.Window(title="Grok Bot 권한 요청")
    win.get_style_context().add_class("grokbot-consent")
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_namespace(win, "grokbot-consent")
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    card.get_style_context().add_class("card")
    if t["sensitive"]:
        card.get_style_context().add_class("sensitive")
    card.set_size_request(520, -1)

    def lab(text, cls, wrap=True):
        lb = Gtk.Label(label=text, xalign=0)
        lb.set_line_wrap(wrap)
        lb.set_max_width_chars(60)
        lb.get_style_context().add_class(cls)
        card.pack_start(lb, False, False, 0)
        return lb

    lab(t["title"], "title")
    for key, pair in (("누가 / Who", t["who"]), ("무엇을 / Scope", t["scope"]),
                      ("어떤 동작 / Action", t["action"])):
        lab(key, "key")
        lab(pair[0], "val")
        if pair[1] != pair[0]:
            lab(pair[1], "en")
    lab(t["call"], "call")
    if t["warning"]:
        w = t["warning"] if isinstance(t["warning"], list) else [t["warning"], t["warning"]]
        lab(w[0], "warn")
        if w[1] != w[0]:
            lab(w[1], "warn-en")
    timer = lab("", "timer")

    row = Gtk.Box(spacing=8)
    row.set_halign(Gtk.Align.END)

    shown = {"t": None}

    def armed():
        # Ignore input for a moment after the prompt appears, so a click or
        # key meant for the window underneath cannot answer it.
        return shown["t"] is not None and time.monotonic() - shown["t"] >= ARM_S

    def done(v):
        answer["v"] = v
        Gtk.main_quit()

    def button(label, cls, value):
        b = Gtk.Button(label=label)
        b.get_style_context().add_class(cls)
        b.connect("clicked", lambda *_: armed() and done(value))
        # Answer on press as well: on some setups (sway + absolute pointers,
        # seen in the VM) the release that completes "clicked" was lost.
        b.connect("button-press-event", lambda _w, ev: (armed() and ev.button == 1 and done(value)) or False)
        row.pack_start(b, False, False, 0)
        return b

    deny = button("거부 / Deny", "deny", "deny")
    if t["once"]:
        button("이번 한 번만 / Allow once", "allow", "once")
    if t["session"]:
        button("이번 세션 동안 / This session", "session", "session")
    if t["always"]:
        button("항상 허용 / Always allow", "always", "always")
    card.pack_start(row, False, False, 6)
    win.add(card)

    def key(_w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            done("deny")
            return True
        if not armed():
            return True  # swallow keys typed for the window underneath
        return False
    win.connect("key-press-event", key)
    win.connect("destroy", lambda *_: done("deny"))

    left = {"s": int(req.get("timeout") or 60)}

    def tick():
        left["s"] -= 1
        timer.set_text("%d초 뒤 자동 거부 / auto-deny in %ds" % (left["s"], left["s"]))
        if left["s"] <= 0:
            done("deny")
            return False
        return True
    tick()
    GLib.timeout_add_seconds(1, tick)
    def reassert():
        # Keep the exclusive keyboard grab: sway hands focus to a window that
        # maps after us unless the layer surface re-commits its mode.
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        win.present()
        return True
    GLib.timeout_add(700, reassert)

    # Arm from when the window is shown. "map-event" is not delivered for
    # layer-shell surfaces here (VM b4: every click and key was swallowed
    # because the prompt never armed), so start the clock at show_all and
    # only move it later if a map signal does arrive.
    def on_map(*_):
        if shown["t"] is None:
            shown["t"] = time.monotonic()
    win.connect("map", on_map)
    win.show_all()
    on_map()
    deny.grab_focus()
    Gtk.main()
    print(answer["v"], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
