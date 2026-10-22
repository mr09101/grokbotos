"""Append-only audit log (JSON lines, mode 0600).

Two files, so that noise anyone can cause cannot push real records out:
  audit.jsonl          RPC calls: allow / deny / prompt answers, grants.
                       Rotated at 5 MB, GENERATIONS old files kept.
  audit-rejects.jsonl  transport-level rejects (bad Host, wrong
                       Content-Type, refused preflight, foreign uid,
                       ignored Origin). Any web page can trigger these
                       (fetch no-cors), so they are aggregated: the first
                       one per (principal, error) per minute is written,
                       the rest are counted and written as one summary
                       line ("count") when the minute is over. At most
                       MAX_KEYS distinct principals per minute; the rest
                       share the principal "*other*".
Every string value is cut to MAX_FIELD characters.
"""
import atexit
import json
import os
import threading
import time

from . import paths

MAX_BYTES = 5 * 1024 * 1024
GENERATIONS = 5
MAX_FIELD = 256
WINDOW = 60
MAX_KEYS = 20
TRANSPORT_ERRORS = frozenset({"bad_host", "content_type", "preflight", "foreign_uid",
                              "origin_untrusted_peer", "app_token_missing", "app_token_bad"})
_lock = threading.Lock()
_window = {"start": 0.0, "counts": {}}


def rejects_path():
    p = paths.audit_path()
    base = p[:-len(".jsonl")] if p.endswith(".jsonl") else p
    return base + "-rejects.jsonl"


def _cap(v):
    if isinstance(v, str) and len(v) > MAX_FIELD:
        return v[:MAX_FIELD] + "…"
    if isinstance(v, dict):
        return {k: _cap(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_cap(x) for x in v]
    return v


def _rotate(path):
    try:
        if os.path.getsize(path) <= MAX_BYTES:
            return
    except OSError:
        return
    for i in range(GENERATIONS - 1, 0, -1):
        try:
            os.replace("%s.%d" % (path, i), "%s.%d" % (path, i + 1))
        except OSError:
            pass
    os.replace(path, path + ".1")


def _write(path, entry):
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    _rotate(path)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def _flush_window(now):
    """Write the summaries of the finished window. Caller holds _lock."""
    w = _window
    for (principal, error), n in sorted(w["counts"].items()):
        if n > 1:
            _write(rejects_path(), {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
                                    "transport": "http", "principal": principal, "decision": "deny",
                                    "error": error, "count": n - 1, "aggregated": True,
                                    "window_start": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                                                  time.localtime(w["start"]))})
    w["counts"] = {}
    w["start"] = now


def record(**fields):
    now = time.time()
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now))}
    entry.update(_cap(fields))
    with _lock:
        if fields.get("error") in TRANSPORT_ERRORS:
            if now - _window["start"] >= WINDOW:
                _flush_window(now)
            counts = _window["counts"]
            key = (entry.get("principal") or "?", entry["error"])
            if key not in counts and len({p for p, _ in counts}) >= MAX_KEYS:
                key = ("*other*", entry["error"])
                entry["principal"] = "*other*"
            counts[key] = counts.get(key, 0) + 1
            if counts[key] == 1:
                _write(rejects_path(), entry)
            return
        _write(paths.audit_path(), entry)


def flush():
    with _lock:
        _flush_window(time.time())


atexit.register(flush)
