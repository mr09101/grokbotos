#!/usr/bin/python3
"""Post-boot health check with automatic rollback (greenboot-style).

Run once per boot by grokbot-health-check.service (root), after the
graphical target. Only a *new* deployment is judged: the image booted for
the first time since an update. It is healthy when, within the timeout,
some user (uid >= 1000) runs sway and that user's grokbotd answers on
/run/user/<uid>/grokbot/api.sock.

  healthy      -> remember its digest as last-good.
  not healthy  -> if this digest has not been rolled back from before and
                  a rollback deployment exists: `bootc rollback`, record
                  why, reboot into the previous image.

Loop guards: a digest is rolled back from at most once (attempts are
kept in /var/lib/grokbot-health/state.json); the last-good image is never
rolled back from; nothing happens without a rollback deployment; and
`grokbot.health=off` on the kernel command line or enabled=false in
/etc/grokbot/health.conf turns it off. The record of a rollback is shown
by grokbotd (update.status, a notification) and Settings > Update.
"""
import configparser
import json
import os
import pwd
import socket
import subprocess
import sys
import time

STATE_DIR = os.environ.get("GROKBOT_HEALTH_DIR", "/var/lib/grokbot-health")
CONF = os.environ.get("GROKBOT_HEALTH_CONF", "/etc/grokbot/health.conf")
CMDLINE = os.environ.get("GROKBOT_HEALTH_CMDLINE", "/proc/cmdline")
PROC = os.environ.get("GROKBOT_HEALTH_PROC", "/proc")
RUNUSER = os.environ.get("GROKBOT_HEALTH_RUNUSER", "/run/user")
BOOTC = os.environ.get("GROKBOT_BOOTC", "bootc")
SYSTEMCTL = os.environ.get("GROKBOT_SYSTEMCTL", "systemctl")


def log(msg):
    print("grokbot-health: " + msg, flush=True)


def load_state():
    try:
        with open(os.path.join(STATE_DIR, "state.json")) as f:
            s = json.load(f)
            return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    os.chmod(STATE_DIR, 0o755)
    tmp = os.path.join(STATE_DIR, "state.json.tmp")
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(STATE_DIR, "state.json"))


def config():
    cp = configparser.ConfigParser()
    cp.read(CONF)
    sec = cp["health"] if cp.has_section("health") else {}
    enabled = str(sec.get("enabled", "true")).lower() not in ("false", "0", "no", "off")
    try:
        with open(CMDLINE) as f:
            if "grokbot.health=off" in f.read().split():
                enabled = False
    except OSError:
        pass
    return enabled, int(sec.get("timeout_s", 300)), int(sec.get("interval_s", 5))


def deployments():
    out = subprocess.run([BOOTC, "status", "--format=json"], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("bootc status failed")
    st = json.loads(out.stdout).get("status") or {}

    def d(k):
        e = st.get(k) or {}
        img = e.get("image") or {}
        return {"digest": img.get("imageDigest"), "version": img.get("version"),
                "image": (img.get("image") or {}).get("image")} if img else None
    return d("booted"), d("rollback")


def _uids_running(name):
    uids = set()
    try:
        pids = [p for p in os.listdir(PROC) if p.isdigit()]
    except OSError:
        return uids
    for pid in pids:
        try:
            with open(os.path.join(PROC, pid, "comm")) as f:
                if f.read().strip() != name:
                    continue
            uid = os.stat(os.path.join(PROC, pid)).st_uid
            if uid >= 1000:
                uids.add(uid)
        except OSError:
            continue
    return uids


def _probe(path):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(3)
    try:
        s.connect(path)
        s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"api.methods"}\n')
        return b'"result"' in s.recv(65536)
    except OSError:
        return False
    finally:
        s.close()


def _api_up(uid):
    """grokbotd only answers its own uid (SO_PEERCRED), so probe as that uid."""
    path = os.path.join(RUNUSER, str(uid), "grokbot", "api.sock")
    if os.getuid() == uid or os.getuid() != 0:
        return _probe(path)
    pid = os.fork()
    if pid == 0:
        try:
            import pwd
            os.setgroups([])
            os.setgid(pwd.getpwuid(uid).pw_gid)
            os.setuid(uid)
            os._exit(0 if _probe(path) else 1)
        except BaseException:
            os._exit(2)
    _, status = os.waitpid(pid, 0)
    return os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0


def healthy():
    """(ok, why) for the session right now."""
    uids = _uids_running("sway")
    if not uids:
        return False, "no sway session"
    for uid in uids:
        if _api_up(uid):
            return True, "sway + grokbotd up for uid %d" % uid
    return False, "sway runs but grokbotd does not answer"


def wait_healthy(timeout, interval, clock=time.monotonic, sleep=time.sleep):
    end = clock() + timeout
    why = "not checked"
    while True:
        ok, why = healthy()
        if ok or clock() >= end:
            return ok, why
        sleep(interval)


def run(clock=time.monotonic, sleep=time.sleep):
    enabled, timeout, interval = config()
    if not enabled:
        log("disabled")
        return 0
    booted, rollback = deployments()
    if not booted or not booted.get("digest"):
        log("no booted image digest; nothing to judge")
        return 0
    st = load_state()
    dig = booted["digest"]
    first_run = "last_good" not in st
    ok, why = wait_healthy(timeout, interval, clock, sleep)
    st["last_check"] = {"digest": dig, "version": booted.get("version"), "ok": ok, "why": why,
                        "at": int(time.time())}
    if ok:
        st["last_good"] = dig
        st["last_good_version"] = booted.get("version")
        save_state(st)
        log("healthy: " + why)
        return 0
    log("NOT healthy after %ds: %s" % (timeout, why))
    if first_run or st.get("last_good") == dig:
        # First boot ever, or an image that was good before: a transient
        # problem, not a bad update. Never roll back from the known-good image.
        save_state(st)
        log("image is the first or last-good one; not rolling back")
        return 1
    attempts = st.setdefault("attempts", {})
    if attempts.get(dig, 0) >= 1:
        save_state(st)
        log("already rolled back from this image once; not again (loop guard)")
        return 1
    if not rollback or not rollback.get("digest") or rollback["digest"] == dig:
        save_state(st)
        log("no rollback deployment; staying")
        return 1
    attempts[dig] = attempts.get(dig, 0) + 1
    st["rolled_back"] = {"from": dig, "from_version": booted.get("version"), "to": rollback["digest"],
                         "to_version": rollback.get("version"), "why": why, "at": int(time.time())}
    save_state(st)
    r = subprocess.run([BOOTC, "rollback"], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        st["rolled_back"]["error"] = (r.stdout + r.stderr).strip()[-300:]
        save_state(st)
        log("bootc rollback failed")
        return 1
    log("rolled back; rebooting into the previous image")
    subprocess.run([SYSTEMCTL, "reboot"])
    return 0


if __name__ == "__main__":
    sys.exit(run())
