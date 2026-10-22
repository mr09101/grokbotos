"""Who is on the other end of the unix socket.

The kernel tells us the peer's pid and uid (SO_PEERCRED, taken at
connect() time, cannot be forged by the peer). From the pid we derive a
stable identity that grants are bound to:

  local:uid=N:unit=<systemd unit>   the process runs in its own unit of
                                    the user's manager (user@N.service):
                                    a .service, or an app-*.scope with
                                    the random suffix removed; system
                                    units fall through to exe/script
  local:uid=N:exe=<path>            otherwise: /proc/<pid>/exe, the
                                    binary the kernel actually runs;
  local:uid=N:exe=<interp>:script=<path>
                                    for interpreters (python, sh, node,
                                    ...) the script they run, resolved
                                    against the process cwd
  local:uid=N:unknown               /proc could not be read (the caller
                                    exited); nothing can be stored for it

What the caller *says* it is (x-client) is only a display label.

Limits (SECURITY.md): a same-uid process can ptrace or LD_PRELOAD
another same-uid program, so this separates honest programs and makes
grants specific; it is not a sandbox. The pid is read once per
connection and checked against the process start time to catch pid
reuse between connect() and our read.
"""
import os
import re

INTERPRETERS = re.compile(r"(python[0-9.]*|bash|sh|dash|zsh|node|nodejs|perl[0-9.]*|ruby[0-9.]*|gjs|lua[0-9.]*)")
_GENERIC_UNITS = re.compile(r"(session-[^/]+\.scope|init\.scope|user@\d+\.service|-\.slice|.*\.slice)")
_SCOPE_SUFFIX = re.compile(r"[-@][0-9a-f]{6,}$|-\d+$")

PROC = "/proc"


def _read(path, binary=False):
    with open(path, "rb" if binary else "r") as f:
        return f.read()


def _start_time(pid):
    stat = _read("%s/%d/stat" % (PROC, pid))
    # field 22, after the ")" that ends comm (comm may contain spaces)
    return stat[stat.rindex(")") + 2:].split()[19]


def unit_of(cgroup_text, uid=None):
    """The systemd unit a process runs in, or None for a plain session.

    Only units of the peer's own per-user manager count (the cgroup path
    goes through user@<uid>.service): those are the apps and services the
    session starts one per program. A process in a system unit (an agent,
    a CI runner, a system service that spawns arbitrary children) is
    identified by its exe/script instead, which is the finer identity.
    """
    path = None
    for line in cgroup_text.splitlines():
        if line.startswith("0::"):
            path = line[3:]
    if not path:
        return None
    parts = path.strip("/").split("/")
    mgr = [i for i, x in enumerate(parts) if re.fullmatch(r"user@(\d+)\.service", x)]
    if not mgr:
        return None
    if uid is not None and parts[mgr[-1]] != "user@%d.service" % uid:
        return None
    last = parts[-1]
    if not last or _GENERIC_UNITS.fullmatch(last):
        return None
    if last.endswith(".scope"):
        stem = last[:-len(".scope")]
        if not stem.startswith("app-"):
            return None
        stem = _SCOPE_SUFFIX.sub("", stem)
        return stem + ".scope"
    if last.endswith(".service"):
        return last
    return None


def script_of(argv, cwd):
    """For an interpreter command line, what it runs."""
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "-m" and i + 1 < len(argv):
            return "module:" + argv[i + 1]
        if a in ("-c", "-e", "--eval"):
            return "inline"
        if a.startswith("-"):
            i += 1
            continue
        p = a if os.path.isabs(a) else os.path.join(cwd or "/", a)
        return os.path.normpath(p)
    return "interactive"


def identify(pid, uid):
    """(principal, details) for a same-uid unix socket peer."""
    base = "local:uid=%d" % uid
    try:
        t0 = _start_time(pid)
        cg = _read("%s/%d/cgroup" % (PROC, pid))
        exe = os.readlink("%s/%d/exe" % (PROC, pid))
        argv = [a.decode("utf-8", "replace") for a in _read("%s/%d/cmdline" % (PROC, pid), True).split(b"\0") if a]
        try:
            cwd = os.readlink("%s/%d/cwd" % (PROC, pid))
        except OSError:
            cwd = "/"
        if _start_time(pid) != t0:
            raise OSError("pid reused")
    except (OSError, ValueError, IndexError):
        return base + ":unknown", {"pid": pid, "uid": uid}
    if exe.endswith(" (deleted)"):
        exe = exe[:-len(" (deleted)")]
    details = {"pid": pid, "uid": uid, "exe": exe}
    unit = unit_of(cg, uid)
    if unit:
        details["unit"] = unit
        return "%s:unit=%s" % (base, unit), details
    if INTERPRETERS.fullmatch(os.path.basename(exe)):
        s = script_of(argv, cwd)
        details["script"] = s
        return "%s:exe=%s:script=%s" % (base, exe, s), details
    return "%s:exe=%s" % (base, exe), details


def describe(principal):
    """Short human name for a local principal (prompt, Settings, dock)."""
    rest = principal.split(":", 2)[2] if principal.count(":") >= 2 else ""
    if rest.startswith("unit="):
        return rest[5:]
    m = re.search(r":script=(.+)$", rest)
    if m:
        s = m.group(1)
        return s[7:] if s.startswith("module:") else os.path.basename(s)
    if rest.startswith("exe="):
        return os.path.basename(rest[4:])
    return rest or "?"
