"""Per-origin tokens for system web apps (<id>.app.localhost).

Any local process can send `Origin: http://settings.app.localhost:7311`
(SECURITY.md), so for app.localhost origins grokbotd also requires an
HttpOnly cookie holding HMAC-SHA256(key, origin). The key is
~/.local/state/grokbot/webapp-key (0600): same-uid host programs can
read it, which gives them nothing new (they may use the unix socket
anyway); other users and Flatpak sandboxes without home access cannot.

The launchers (grokbot-webapp, grokbot-settings) open
<start_url>?gbt=<token>; grokbotd checks it, sets the cookie and
redirects to the clean URL, so pages never see the token.
"""
import hashlib
import hmac
import os
import secrets

from . import paths

COOKIE = "gbt"
PARAM = "gbt"


def key_path():
    return os.environ.get("GROKBOT_WEBAPP_KEY") or os.path.join(paths.state_home(), "grokbot", "webapp-key")


def _key():
    p = key_path()
    try:
        with open(p, "rb") as f:
            k = f.read()
        if len(k) >= 32:
            return k
    except OSError:
        pass
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    k = secrets.token_bytes(32)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, k)
    finally:
        os.close(fd)
    try:
        os.link(tmp, p)  # first writer wins; a racing one reads it back
    except FileExistsError:
        pass
    finally:
        os.unlink(tmp)
    with open(p, "rb") as f:
        return f.read()


def token(origin):
    return hmac.new(_key(), origin.lower().encode("utf-8"), hashlib.sha256).hexdigest()


def valid(origin, value):
    if not value or len(value) != 64:
        return False
    return hmac.compare_digest(token(origin), value)


def cookie_value(cookie_header):
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return None


if __name__ == "__main__":
    import sys
    print(token(sys.argv[1]))
