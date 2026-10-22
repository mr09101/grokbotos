"""display.list / display.set: outputs (monitors) via sway IPC.

Changes apply immediately through `output` commands and are saved to
~/.config/grokbot/outputs.conf, which /etc/sway/config includes, so they
survive a restart.
"""
import json
import os
import re

from . import paths, sway
from .backends import BackendError

NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def conf_path():
    return os.path.join(paths.config_home(), "grokbot", "outputs.conf")


def _norm(o):
    cm = o.get("current_mode") or {}
    r = o.get("rect") or {}
    return {
        "name": o.get("name"),
        "make": o.get("make") or "",
        "model": o.get("model") or "",
        "active": bool(o.get("active")),
        "focused": bool(o.get("focused")),
        "scale": o.get("scale") if o.get("active") else None,
        "transform": o.get("transform") or "normal",
        "x": r.get("x", 0), "y": r.get("y", 0),
        "width": r.get("width", 0), "height": r.get("height", 0),
        "mode": {"width": cm.get("width"), "height": cm.get("height"),
                 "refresh": round((cm.get("refresh") or 0) / 1000.0, 3)} if cm else None,
        "modes": [{"width": m.get("width"), "height": m.get("height"),
                   "refresh": round((m.get("refresh") or 0) / 1000.0, 3)}
                  for m in (o.get("modes") or [])],
    }


def outputs():
    try:
        return [_norm(o) for o in sway.call(sway.GET_OUTPUTS)]
    except sway.SwayUnavailable as e:
        raise BackendError("sway is not reachable: %s" % e)


def display_list(_params):
    outs = outputs()
    return {"outputs": outs, "saved": load_saved()}


def load_saved():
    """{name: {scale, x, y, enabled, mode}} from outputs.conf (our own format)."""
    p = conf_path()
    try:
        with open(p) as f:
            for line in f:
                if line.startswith("# grokbot-outputs "):
                    return json.loads(line[len("# grokbot-outputs "):])
    except (OSError, ValueError):
        pass
    return {}


def _line(name, s):
    parts = ['output "%s"' % name]
    if s.get("enabled") is False:
        return parts[0] + " disable"
    if "mode" in s and s["mode"]:
        m = s["mode"]
        parts.append("mode %dx%d" % (m["width"], m["height"]) +
                     ("@%sHz" % m["refresh"] if m.get("refresh") else ""))
    if "scale" in s:
        parts.append("scale %s" % s["scale"])
    if "x" in s and "y" in s:
        parts.append("position %d %d" % (s["x"], s["y"]))
    if s.get("enabled") is True:
        parts.append("enable")
    return " ".join(parts)


def save(saved):
    p = conf_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    body = ["# Written by grokbotd (Settings > Display). Do not edit by hand.",
            "# grokbot-outputs " + json.dumps(saved, sort_keys=True)]
    body += [_line(n, s) for n, s in sorted(saved.items())]
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(body) + "\n")
    os.replace(tmp, p)


def display_set(params):
    name = params["name"]
    if not NAME_RE.match(name):
        raise BackendError("bad output name")
    outs = {o["name"]: o for o in outputs()}
    if name not in outs:
        raise BackendError("no such output: %s" % name)
    o = outs[name]
    s = {}
    if "scale" in params:
        sc = float(params["scale"])
        if not 0.5 <= sc <= 4:
            raise BackendError("scale must be 0.5-4")
        s["scale"] = round(sc * 8) / 8  # whole 1/8 steps, like sway
    if "x" in params or "y" in params:
        s["x"] = int(params.get("x", o["x"]))
        s["y"] = int(params.get("y", o["y"]))
    if "mode" in params:
        m = params["mode"]
        if not any(mm["width"] == m["width"] and mm["height"] == m["height"] for mm in o["modes"]) and o["modes"]:
            raise BackendError("mode %dx%d is not offered by %s" % (m["width"], m["height"], name))
        s["mode"] = {"width": int(m["width"]), "height": int(m["height"]), "refresh": m.get("refresh")}
    if "enabled" in params:
        if not params["enabled"] and sum(1 for x in outs.values() if x["active"]) <= 1 and o["active"]:
            raise BackendError("refusing to turn off the last screen")
        s["enabled"] = bool(params["enabled"])
    if not s:
        raise BackendError("nothing to change")
    cmd = _line(name, s)
    try:
        res = sway.call(sway.RUN_COMMAND, cmd.encode())
    except sway.SwayUnavailable as e:
        raise BackendError("sway is not reachable: %s" % e)
    bad = [r.get("error") for r in res if not r.get("success")]
    if bad:
        raise BackendError("sway refused: %s" % "; ".join(str(b) for b in bad))
    saved = load_saved()
    merged = dict(saved.get(name, {}))
    merged.update(s)
    saved[name] = merged
    save(saved)
    return {"command": cmd, "outputs": outputs()}


METHODS = {
    "display.list": display_list,
    "display.set": display_set,
}
