"""update.* : OS updates with rollback (bootc), docs/OS_UPDATES.md.

grokbotd runs as the session user, bootc needs root. So grokbotd only
reads what the root units write (/run/grokbot-update/*.json and the
health record /var/lib/grokbot-health/state.json) and starts one of four
units, grokbot-update@{status,check,apply,rollback}.service, which polkit
lets the active local user start (and nothing else). The "updates" scope
is in perms.ALWAYS_ASK: check, apply and rollback prompt every time.
"""
import json
import os
import subprocess
import threading
import time

from . import paths
from .backends import BackendError

ACTIONS = ("check", "apply", "rollback")


def run_dir():
    return os.environ.get("GROKBOT_UPDATE_RUN", "/run/grokbot-update")


def health_dir():
    return os.environ.get("GROKBOT_HEALTH_DIR", "/var/lib/grokbot-health")


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _systemctl(*args, timeout=10):
    try:
        r = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def running():
    out = []
    for a in ("status",) + ACTIONS:
        rc, txt = _systemctl("is-active", "grokbot-update@%s.service" % a)
        if txt.splitlines()[-1:] in (["activating"], ["active"], ["reloading"]):
            out.append(a)
    return out


def status(params=None):
    rd = run_dir()
    st = _read(os.path.join(rd, "status.json"))
    if st is None:
        _systemctl("start", "--no-block", "grokbot-update@status.service")
    chk = _read(os.path.join(rd, "check.json"))
    last = _read(os.path.join(rd, "last.json"))
    h = _read(os.path.join(health_dir(), "state.json")) or {}
    st = st or {}
    avail = bool(chk and chk.get("available"))
    if avail and st.get("staged") and st["staged"].get("digest") == chk.get("digest"):
        avail = False
    return {
        "booted": st.get("booted"), "staged": st.get("staged"), "rollback": st.get("rollback"),
        "rollback_queued": bool(st.get("rollback_queued")),
        "restart_needed": bool(st.get("staged") or st.get("rollback_queued")),
        "available": avail,
        "available_version": chk.get("version") if avail else None,
        "available_digest": chk.get("digest") if avail else None,
        "checked_at": chk and chk.get("checked_at"),
        "last": last, "running": running(),
        "health": {"last_good": h.get("last_good"), "last_good_version": h.get("last_good_version"),
                   "last_check": h.get("last_check"), "rolled_back": h.get("rolled_back")},
        "known": bool(st),
    }


def _start(action):
    busy = running()
    if [a for a in busy if a != "status"]:
        raise BackendError("an update action is already running: %s" % ", ".join(busy))
    rc, txt = _systemctl("start", "--no-block", "grokbot-update@%s.service" % action)
    if rc != 0:
        raise BackendError("could not start the %s unit: %s" % (action, txt[-200:]))
    return {"started": action, "unit": "grokbot-update@%s.service" % action}


def check(params):
    return _start("check")


def apply(params):
    return _start("apply")


def rollback(params):
    return _start("rollback")


METHODS = {"update.status": status, "update.check": check, "update.apply": apply, "update.rollback": rollback}


# ---- notifications (once per new update / once per automatic rollback) ----

def _seen_path():
    return os.path.join(paths.state_home(), "grokbot", "update-notified.json")


def _notify(summary, body, urgency="normal"):
    try:
        subprocess.run(["notify-send", "-a", "Grok Bot OS", "-u", urgency, "-t", "60000", "-i", "system-software-update",
                        summary, body], timeout=5, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass


def notify_once(send=_notify):
    """Notify about a new available update or an automatic rollback, once each."""
    seen = _read(_seen_path()) or {}
    changed = False
    s = status()
    if s["available"] and s.get("available_digest") and seen.get("available") != s["available_digest"]:
        v = s.get("available_version") or s["available_digest"][:19]
        send("업데이트가 있습니다 / Update available",
             "새 OS 이미지 %s. 설정 > 업데이트에서 설치할 수 있습니다. / New OS image %s: Settings > Update." % (v, v))
        seen["available"] = s["available_digest"]
        changed = True
    rb = s["health"].get("rolled_back")
    if rb and seen.get("rolled_back") != rb.get("at"):
        v = rb.get("from_version") or (rb.get("from") or "")[:19]
        send("업데이트를 되돌렸습니다 / Update rolled back",
             "%s 이미지로 시작한 뒤 세션이 뜨지 않아 이전 이미지로 되돌렸습니다 (%s). / The session did not come up on %s, "
             "so the previous image was restored." % (v, rb.get("why"), v), "critical")
        seen["rolled_back"] = rb.get("at")
        changed = True
    if changed:
        os.makedirs(os.path.dirname(_seen_path()), exist_ok=True)
        with open(_seen_path(), "w") as f:
            json.dump(seen, f)
    return changed


def watch(stop, interval=60):
    def loop():
        while not stop.wait(5 if not getattr(loop, "ran", False) else interval):
            loop.ran = True
            try:
                notify_once()
            except Exception:  # never take the daemon down
                pass
    t = threading.Thread(target=loop, name="update-notify", daemon=True)
    t.start()
    return t
