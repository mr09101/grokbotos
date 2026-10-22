#!/usr/bin/python3
"""Root side of OS updates: grokbot_update.py status|check|apply|rollback

Runs only from the grokbot-update@<action>.service units (root). The
session user may start those four units (polkit rule
50-grokbot-update.rules) but nothing else, and grokbotd asks the user
before starting check / apply / rollback. Results go to
/run/grokbot-update/*.json (world-readable, no secrets):

  status.json  bootc status: booted / staged / rollback images
  check.json   last check: available?, the new image's version and digest
  last.json    last action: what, when, ok, message

apply = `bootc upgrade` (download + stage; the new image boots at the next
restart, the current one stays as rollback). rollback = `bootc rollback`
(the rollback image boots at the next restart). Neither reboots.
"""
import fcntl
import json
import os
import subprocess
import sys
import time

RUN = os.environ.get("GROKBOT_UPDATE_RUN", "/run/grokbot-update")
BOOTC = os.environ.get("GROKBOT_BOOTC", "bootc")
ACTIONS = ("status", "check", "apply", "rollback")


def _write(name, doc):
    os.makedirs(RUN, exist_ok=True)
    os.chmod(RUN, 0o755)
    tmp = os.path.join(RUN, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(RUN, name))


def _read(name):
    try:
        with open(os.path.join(RUN, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _bootc(*args, timeout=3600):
    r = subprocess.run([BOOTC, *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def entry(e):
    """One deployment from bootc status JSON -> our flat form."""
    if not e:
        return None
    img = e.get("image") or {}
    ref = (img.get("image") or {})
    return {"image": ref.get("image"), "transport": ref.get("transport"),
            "version": img.get("version"), "timestamp": img.get("timestamp"),
            "digest": img.get("imageDigest"), "pinned": bool(e.get("pinned"))}


def summarize(doc):
    st = (doc or {}).get("status") or {}
    booted = st.get("booted") or {}
    cached = booted.get("cachedUpdate")
    return {"booted": entry(booted), "staged": entry(st.get("staged")),
            "rollback": entry(st.get("rollback")), "rollback_queued": bool(st.get("rollbackQueued")),
            "cached_update": {"version": cached.get("version"), "digest": cached.get("imageDigest"),
                              "timestamp": cached.get("timestamp")} if cached else None,
            "spec_image": (((doc or {}).get("spec") or {}).get("image") or {}).get("image")}


def status():
    rc, out = _bootc("status", "--format=json", timeout=120)
    if rc != 0:
        raise RuntimeError("bootc status failed: " + out.strip()[-300:])
    s = summarize(json.loads(out))
    s["updated_at"] = int(time.time())
    _write("status.json", s)
    return s


def available(s):
    """New image known from the last check that is neither booted nor staged."""
    c = s.get("cached_update")
    if not c or not c.get("digest"):
        return None
    for k in ("booted", "staged"):
        if s.get(k) and s[k].get("digest") == c["digest"]:
            return None
    return c


def check():
    rc, out = _bootc("upgrade", "--check", timeout=900)
    if rc != 0:
        raise RuntimeError("bootc upgrade --check failed: " + out.strip()[-300:])
    s = status()
    a = available(s)
    _write("check.json", {"checked_at": int(time.time()), "available": bool(a),
                          "version": a and a.get("version"), "digest": a and a.get("digest"),
                          "output": out.strip()[-500:]})
    return "update available: %s" % (a.get("version") or a.get("digest")) if a else "up to date"


def apply():
    rc, out = _bootc("upgrade", timeout=7200)
    if rc != 0:
        raise RuntimeError("bootc upgrade failed: " + out.strip()[-300:])
    s = status()
    c = _read("check.json") or {}
    c.update(available=False, staged=True)
    _write("check.json", c)
    st = s.get("staged")
    return "staged %s; restart to use it" % (st and (st.get("version") or st.get("digest"))) if st else out.strip()[-200:]


def rollback():
    rc, out = _bootc("rollback", timeout=600)
    if rc != 0:
        raise RuntimeError("bootc rollback failed: " + out.strip()[-300:])
    status()
    return "rollback queued; restart to use the previous image"


def main(argv):
    if len(argv) != 1 or argv[0] not in ACTIONS:
        sys.stderr.write("usage: grokbot_update.py %s\n" % "|".join(ACTIONS))
        return 2
    act = argv[0]
    os.makedirs(RUN, exist_ok=True)
    with open(os.path.join(RUN, ".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        started = int(time.time())
        try:
            msg = {"status": lambda: (status(), "ok")[1], "check": check,
                   "apply": apply, "rollback": rollback}[act]()
            ok = True
        except Exception as e:  # recorded for the UI, exit non-zero for systemd
            msg, ok = str(e), False
        if act != "status":
            _write("last.json", {"action": act, "started": started, "finished": int(time.time()),
                                 "ok": ok, "message": msg})
        print(msg)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
