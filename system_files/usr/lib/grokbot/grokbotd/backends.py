"""Read-only implementations of the API methods.

Each function takes validated params and returns a JSON-serialisable
dict. Nothing here writes to the system.
"""
import configparser
import glob
import ipaddress
import json
import os
import time
import platform
import socket
import subprocess

from . import capture, inputmethod, lock, media, notify, paths, sway


class BackendError(RuntimeError):
    pass


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def _os_release():
    out = {}
    for p in ("/etc/os-release", "/usr/lib/os-release"):
        text = _read(p)
        if text:
            for line in text.splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    out[k] = v.strip().strip('"')
            break
    return out


def _bootc_image():
    """Image reference of the booted deployment, without root.

    The ostree origin file of each deployment is world-readable and
    carries container-image-reference=. /run/ostree-booted marks a booted
    ostree system."""
    if not os.path.exists("/run/ostree-booted"):
        return None
    for origin in sorted(glob.glob("/sysroot/ostree/deploy/*/deploy/*.origin")):
        text = _read(origin, "")
        for line in text.splitlines():
            if line.startswith("container-image-reference="):
                return line.split("=", 1)[1]
    return "unknown"


def system_info(params):
    osr = _os_release()
    mem = {}
    for line in (_read(os.path.join(paths.procfs(), "meminfo"), "") or "").splitlines():
        k, _, v = line.partition(":")
        if k in ("MemTotal", "MemAvailable"):
            mem[k] = int(v.split()[0]) * 1024
    up = _read(os.path.join(paths.procfs(), "uptime"), "0 0").split()[0]
    return {
        "os": {"name": osr.get("NAME"), "pretty_name": osr.get("PRETTY_NAME"),
               "version": osr.get("VERSION_ID"), "variant_id": osr.get("VARIANT_ID"),
               "id": osr.get("ID")},
        "kernel": platform.release(),
        "arch": platform.machine(),
        "hostname": socket.gethostname(),
        "uptime_s": int(float(up)),
        "memory": {"total_bytes": mem.get("MemTotal"), "available_bytes": mem.get("MemAvailable")},
        "cpus": os.cpu_count(),
        "bootc_image": _bootc_image(),
        "session": {"wayland_display": _wayland_display(),
                    "sway_running": _sway_ok()},
    }


def _wayland_display():
    # The user service may start before sway exports WAYLAND_DISPLAY.
    d = os.environ.get("WAYLAND_DISPLAY")
    if d:
        return d
    socks = sorted(os.path.basename(p) for p in glob.glob(os.path.join(paths.runtime_dir(), "wayland-*"))
                   if not p.endswith(".lock"))
    return socks[0] if socks else None


def _sway_ok():
    try:
        sway.socket_path()
        return True
    except sway.SwayUnavailable:
        return False


def windows_list(params):
    try:
        wins = sway.windows_from_tree(sway.call(sway.GET_TREE))
    except sway.SwayUnavailable as e:
        raise BackendError("sway unavailable: %s" % e)
    ws = params.get("workspace")
    if ws is not None:
        wins = [w for w in wins if w["workspace"] == ws]
    return {"windows": wins}


def workspaces_list(params):
    try:
        wss = sway.call(sway.GET_WORKSPACES)
    except sway.SwayUnavailable as e:
        raise BackendError("sway unavailable: %s" % e)
    return {"workspaces": [
        {"name": w.get("name"), "num": w.get("num"), "output": w.get("output"),
         "focused": bool(w.get("focused")), "visible": bool(w.get("visible")),
         "urgent": bool(w.get("urgent"))} for w in wss]}


def _ini(files, section):
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(files)
    return dict(cp[section]) if cp.has_section(section) else {}


def dock_get(params):
    c = _ini(paths.dock_confs(), "dock")
    try:
        size = int(c.get("icon_size", "40"))
    except ValueError:
        size = 40
    return {
        "top": c.get("top", "off"), "bottom": c.get("bottom", "icons"),
        "left": c.get("left", "off"), "right": c.get("right", "off"),
        "icon_size": size,
        "hide": [h for h in c.get("hide", "").split(";") if h],
        "status": c.get("status", "auto"),
    }


def wallpaper_get(params):
    c = _ini(paths.desktop_confs(), "desktop")
    wp = c.get("wallpaper", "")
    return {"wallpaper": wp, "mode": c.get("mode", "fill"),
            "color": c.get("color", "#000000"),
            "exists": bool(wp) and os.path.isfile(wp)}


def _desktop_entries():
    seen, out = set(), []
    for d in paths.xdg_data_dirs():
        for f in sorted(glob.glob(os.path.join(d, "applications", "*.desktop"))):
            did = os.path.basename(f)
            if did in seen:
                continue  # earlier dirs override later ones, like XDG lookup
            seen.add(did)
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
            except (configparser.Error, UnicodeDecodeError):
                continue
            if not cp.has_section("Desktop Entry"):
                continue
            e = cp["Desktop Entry"]
            if e.get("Type", "Application") != "Application":
                continue
            if e.get("NoDisplay", "false").lower() == "true" or e.get("Hidden", "false").lower() == "true":
                continue
            out.append({"desktop_id": did, "name": e.get("Name"), "icon": e.get("Icon"),
                        "path": f})
    return out


def apps_list(params):
    installed = []
    for f in sorted(glob.glob(os.path.join(paths.installed_dir(), "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                rec = json.load(fh)
            if isinstance(rec, dict):
                installed.append({k: rec.get(k) for k in ("id", "kind", "name")})
        except (OSError, ValueError):
            continue
    from . import webapps
    out = {"installed": installed, "webapps": [webapps.public(a) for a in webapps.all_apps()]}
    if params.get("include_launchers", True):
        out["launchers"] = _desktop_entries()
    return out


_cpu_last = {}


def _cpu_times():
    line = (_read(os.path.join(paths.procfs(), "stat"), "") or "").splitlines()
    out = {}
    for l in line:
        if l.startswith("cpu"):
            f = l.split()
            vals = [int(x) for x in f[1:9]]
            idle = vals[3] + vals[4]
            out[f[0]] = (sum(vals), idle)
    return out


def system_resources(params):
    """CPU (percent since the previous call, at most 60 s ago), load,
    memory, swap, disks and network byte counters."""
    now = time.time()
    cur = _cpu_times()
    prev = _cpu_last.get("v")
    cpu = {"percent": None, "per_cpu": []}
    if prev and now - _cpu_last.get("t", 0) <= 60:
        def pct(k):
            if k not in prev[1] or k not in cur:
                return None
            dt, di = cur[k][0] - prev[1][k][0], cur[k][1] - prev[1][k][1]
            return round(100.0 * (dt - di) / dt, 1) if dt > 0 else 0.0
        cpu["percent"] = pct("cpu")
        cpu["per_cpu"] = [pct(k) for k in sorted((k for k in cur if k != "cpu"), key=lambda k: int(k[3:]))]
    if not prev or now - _cpu_last.get("t", 0) >= 0.5:
        _cpu_last.update(v=(now, cur), t=now)
    if prev is None:
        pass
    mem = {}
    for line in (_read(os.path.join(paths.procfs(), "meminfo"), "") or "").splitlines():
        k, _, v = line.partition(":")
        if k in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree", "Cached", "Buffers"):
            mem[k] = int(v.split()[0]) * 1024
    load = (_read(os.path.join(paths.procfs(), "loadavg"), "0 0 0") or "0 0 0").split()[:3]
    disks = []
    seen = set()
    for mp in ("/", "/var", "/var/home", os.path.expanduser("~")):
        try:
            st = os.statvfs(mp)
        except OSError:
            continue
        key = (st.f_blocks, st.f_bfree, st.f_files)
        if key in seen:
            continue
        seen.add(key)
        disks.append({"mount": mp, "total_bytes": st.f_blocks * st.f_frsize,
                      "free_bytes": st.f_bavail * st.f_frsize,
                      "used_bytes": (st.f_blocks - st.f_bfree) * st.f_frsize})
    net = []
    for line in (_read(os.path.join(paths.procfs(), "net", "dev"), "") or "").splitlines()[2:]:
        name, _, rest = line.partition(":")
        f = rest.split()
        if len(f) >= 9 and name.strip() != "lo":
            net.append({"name": name.strip(), "rx_bytes": int(f[0]), "tx_bytes": int(f[8])})
    return {"time": now, "cpu": cpu, "cpus": os.cpu_count(),
            "load": [float(x) for x in load],
            "memory": {"total_bytes": mem.get("MemTotal"), "available_bytes": mem.get("MemAvailable"),
                       "swap_total_bytes": mem.get("SwapTotal"), "swap_free_bytes": mem.get("SwapFree")},
            "disks": disks, "network": net}


def power_status(params):
    base = os.path.join(paths.sysfs(), "class", "power_supply")
    bats, on_ac = [], None
    for d in sorted(glob.glob(os.path.join(base, "*"))):
        typ = _read(os.path.join(d, "type"))
        if typ == "Battery":
            cap = _read(os.path.join(d, "capacity"))
            bats.append({"name": os.path.basename(d),
                         "capacity_percent": int(cap) if cap and cap.isdigit() else None,
                         "status": _read(os.path.join(d, "status"))})
        elif typ in ("Mains", "USB"):
            online = _read(os.path.join(d, "online"))
            if online is not None:
                on_ac = bool(on_ac) or online == "1"
    if on_ac is None and not bats:
        on_ac = True  # desktops and VMs without a power_supply class
    return {"batteries": bats, "on_ac": on_ac}


def _addresses():
    try:
        out = subprocess.run(["ip", "-j", "addr"], capture_output=True, text=True,
                             timeout=3, check=True).stdout
        return {i["ifname"]: [a["local"] + "/" + str(a["prefixlen"])
                              for a in i.get("addr_info", []) if "local" in a]
                for i in json.loads(out)}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return {}


def _default_route():
    text = _read(os.path.join(paths.procfs(), "net", "route"), "") or ""
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) > 2 and f[1] == "00000000":
            gw = str(ipaddress.IPv4Address(bytes.fromhex(f[2])[::-1]))
            return {"interface": f[0], "gateway": gw}
    return None


def network_status(params):
    base = os.path.join(paths.sysfs(), "class", "net")
    addrs = _addresses()
    ifs = []
    for d in sorted(glob.glob(os.path.join(base, "*"))):
        name = os.path.basename(d)
        ifs.append({"name": name, "state": _read(os.path.join(d, "operstate")),
                    "mac": _read(os.path.join(d, "address")),
                    "wireless": os.path.isdir(os.path.join(d, "wireless")),
                    "addresses": addrs.get(name, [])})
    route = _default_route()
    return {"interfaces": ifs, "default_route": route, "online": route is not None}


METHODS = {
    "system.info": system_info,
    "system.resources": system_resources,
    "windows.list": windows_list,
    "workspaces.list": workspaces_list,
    "dock.get": dock_get,
    "wallpaper.get": wallpaper_get,
    "apps.list": apps_list,
    "power.status": power_status,
    "network.status": network_status,
    "lock.status": lock.lock_status,
    "audio.status": media.audio_status,
    "display.brightness": media.display_brightness,
    "notifications.list": notify.notifications_list,
    "capture.status": capture.capture_status,
    "input.status": inputmethod.input_status,
}
