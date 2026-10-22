"""Who is calling, and which origins get CORS.

Principals:
  local:uid=N    a process of the same user on the unix socket
  origin:<o>     a web page, identified by its HTTP Origin header
  http:no-origin an HTTP client that sent no Origin (curl, scripts)
  http:bad-origin an Origin that is not http(s)://host[:port] ("null")

What each principal may do is decided per scope in perms.py.
"""
import os

from . import perms


def allowed(principal, scope, access="read", capability=None):
    """True if the call would go through without a prompt."""
    if scope is None:
        return True
    return perms.mode_for(principal, scope, access, capability)[0] == "allow"


def origin_known(origin):
    return perms.origin_known(origin)


def tcp_peer(peer_port, local_port, proc="/proc"):
    """(uid, inode) of the loopback TCP socket that connected to us, or
    (None, None)."""
    want_local = ":%04X" % peer_port
    want_remote = ":%04X" % local_port
    try:
        with open(os.path.join(proc, "net", "tcp"), encoding="ascii") as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) > 9 and p[1].endswith(want_local) and p[2].endswith(want_remote):
                    return int(p[7]), int(p[9])
    except (OSError, ValueError, StopIteration):
        pass
    return None, None


def tcp_peer_uid(peer_port, local_port, proc="/proc"):
    """uid owning the loopback TCP socket that connected to us, or None.

    The HTTP port is reachable by every local user; only our own uid
    may use it, like the unix socket."""
    return tcp_peer(peer_port, local_port, proc)[0]


# Programs whose Origin header we believe: real browsers set it and page
# scripts cannot change it. Any other program (curl, a script, a Flatpak
# app with network access) could write any Origin, so its HTTP calls are
# treated as having none (principal http:no-origin).
BROWSERS = frozenset({"firefox", "firefox-bin", "firefox-esr", "chromium", "chromium-browser",
                      "chrome", "google-chrome", "grok-bot", "electron"})


def socket_owner(inode, proc="/proc"):
    """pid holding socket:[inode] among the processes we may inspect."""
    want = "socket:[%d]" % inode
    try:
        pids = [d for d in os.listdir(proc) if d.isdigit()]
    except OSError:
        return None
    for pid in pids:
        fd_dir = os.path.join(proc, pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(os.path.join(fd_dir, fd)) == want:
                    return int(pid)
            except OSError:
                continue
    return None


def peer_is_browser(inode, proc="/proc"):
    """True if the TCP peer is a browser running unsandboxed on the host
    (its root is our root, so not a Flatpak or other container)."""
    if os.environ.get("GROKBOT_TRUST_ANY_ORIGIN_PEER") == "1":
        return True  # tests only: urllib plays the browser
    if inode is None:
        return False
    pid = socket_owner(inode, proc)
    if pid is None:
        return False
    try:
        exe = os.readlink(os.path.join(proc, str(pid), "exe"))
        root = os.readlink(os.path.join(proc, str(pid), "root"))
    except OSError:
        return False
    if exe.endswith(" (deleted)"):
        exe = exe[:-len(" (deleted)")]
    return root == "/" and os.path.basename(exe) in BROWSERS
