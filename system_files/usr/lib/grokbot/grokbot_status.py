"""Status items for the dock: camera/microphone in use, Wi-Fi, volume,
battery, clock.

Data comes from grokbotd (privacy.status, power.status, network.status, audio.status)
over the user's unix socket, so the dock is just another OS API client.
No GTK here, so it can be unit-tested.
"""
import json
import os
import socket
import time

EDGES = ("top", "bottom", "left", "right")


def socket_path():
    return os.environ.get("GROKBOT_API_SOCK") or os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "grokbot", "api.sock")


def rpc(method, timeout=1.0):
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(timeout)
        s.connect(socket_path())
        f = s.makefile("rwb")
        f.write((json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}) + "\n").encode())
        f.flush()
        r = json.loads(f.readline() or b"{}")
        s.close()
        return r.get("result")
    except (OSError, ValueError):
        return None


def status_edge(conf):
    """Which edge shows the status area, or None."""
    want = conf.get("status", "auto")
    if want == "off":
        return None
    if want in EDGES:
        return want if conf.get(want, "off") != "off" else None
    for e in ("bottom", "top", "right", "left"):
        if conf.get(e, "off") != "off":
            return e
    return None


def _battery(power):
    if not power or not power.get("batteries"):
        return None
    b = power["batteries"][0]
    cap = b.get("capacity_percent")
    status = (b.get("status") or "").lower()
    on_ac = bool(power.get("on_ac"))
    # Charging and Discharging come from the kernel status string.
    # Anything else while on AC (Unknown, empty, None, Not charging, Full)
    # still means the adapter is connected. Some ACPI and charge-threshold
    # laptops never leave Unknown.
    charging = status == "charging"
    discharging = status == "discharging"
    plugged = on_ac and not charging and not discharging
    if cap is None:
        level, pct = None, "?"
    else:
        level = min(100, max(0, int(round(cap / 10.0)) * 10))
        pct = "%s%%" % cap
    if charging:
        icon = "battery-missing-symbolic" if level is None else "battery-level-%d-charging-symbolic" % level
        text = "충전 중"
        tip = "충전 중 / Charging %s" % pct
    elif plugged:
        if status == "full":
            # Adwaita status icon: full battery plus a charged mark.
            # Not charging keeps the plug (ac-adapter-symbolic) so an
            # icon-only dock can tell the two apart.
            icon = "battery-level-100-charged-symbolic"
            text, tip = "전원 연결됨 (가득 참)", "전원 연결됨 (가득 참) / Plugged in (full)"
        else:
            icon = "ac-adapter-symbolic"
            text, tip = "전원 연결됨", "전원 연결됨 / Plugged in %s" % pct
    else:
        icon = "battery-missing-symbolic" if level is None else "battery-level-%d-symbolic" % level
        text = pct
        tip = "배터리 / Battery %s" % pct
    return {"id": "battery", "icon": icon, "text": text, "tooltip": tip}


def _network(net):
    if net is None:
        return None
    ifs = [i for i in net.get("interfaces", []) if i.get("name") != "lo"]
    route = net.get("default_route") or {}
    up = [i for i in ifs if i.get("state") == "up" and i.get("addresses")]
    dev = next((i for i in up if i.get("name") == route.get("interface")), up[0] if up else None)
    if not net.get("online") or dev is None:
        return {"id": "network", "icon": "network-offline-symbolic", "text": "오프라인",
                "tooltip": "연결 안 됨 / Offline. 클릭: Wi-Fi 설정 / Click: Wi-Fi settings"}
    if dev.get("wireless"):
        return {"id": "network", "icon": "network-wireless-signal-good-symbolic", "text": "Wi-Fi",
                "tooltip": "Wi-Fi: %s" % dev["name"]}
    return {"id": "network", "icon": "network-wired-symbolic", "text": "유선",
            "tooltip": "유선 / Wired: %s" % dev["name"]}


def _volume(audio):
    if not audio or not audio.get("available") or not audio.get("output"):
        return None
    o = audio["output"]
    v = o.get("volume_percent") or 0
    if o.get("muted") or v == 0:
        icon = "audio-volume-muted-symbolic"
    elif v < 34:
        icon = "audio-volume-low-symbolic"
    elif v < 67:
        icon = "audio-volume-medium-symbolic"
    else:
        icon = "audio-volume-high-symbolic"
    text = "음소거" if o.get("muted") else "%d%%" % v
    return {"id": "volume", "icon": icon, "text": text,
            "tooltip": "볼륨 / Volume %s. 클릭: 음소거, 스크롤: 조절 / Click: mute, scroll: adjust" % text}


def _who(sess):
    p = sess.get("principal") or "?"
    name = p[7:] if p.startswith("origin:") else ("이 컴퓨터 / local" if p.startswith("local:") else p)
    return name + (" (%s)" % sess["client"] if sess.get("client") else "")


def _privacy(priv):
    """Camera / microphone in-use indicators (privacy.status). Shown
    first, highlighted, for as long as a use session is open."""
    if not priv:
        return []
    out = []
    for kind, icon, ko, en in (("camera", "camera-web-symbolic", "카메라 사용 중", "Camera in use"),
                               ("microphone", "audio-input-microphone-symbolic", "마이크 사용 중",
                                "Microphone in use")):
        ss = [x for x in priv.get("sessions", []) if x.get("kind") == kind]
        if ss:
            out.append({"id": "inuse-" + kind, "icon": icon, "text": ko, "alert": True,
                        "tooltip": "%s / %s: %s. 클릭: 권한 / Click: permissions" % (ko, en, ", ".join(_who(x) for x in ss))})
    return out


def _update(up):
    """OS update indicator: an update is available, or one is staged and
    needs a restart. Nothing when up to date (or update.status missing)."""
    if not up:
        return None
    if up.get("restart_needed"):
        return {"id": "update", "icon": "system-reboot-symbolic", "text": "다시 시작 필요",
                "tooltip": "업데이트가 준비됐습니다. 다시 시작하면 적용됩니다 / Update ready: restart to use it. "
                           "클릭: 업데이트 / Click: Update"}
    if up.get("available"):
        v = up.get("available_version") or ""
        return {"id": "update", "icon": "software-update-available-symbolic", "text": "업데이트", "alert": True,
                "tooltip": "OS 업데이트가 있습니다 %s / OS update available %s. 클릭: 업데이트 / Click: Update" % (v, v)}
    return None


def clock(now=None):
    t = time.localtime(now)
    return {"id": "clock", "icon": None, "text": time.strftime("%H:%M", t),
            "tooltip": time.strftime("%Y-%m-%d (%a) %H:%M", t)}


def items(call=rpc, now=None):
    """Status items in display order; missing data drops the item."""
    out = _privacy(call("privacy.status")) + [
        _network(call("network.status")), _volume(call("audio.status")),
        _battery(call("power.status")), _update(call("update.status")), clock(now)]
    return [i for i in out if i]
