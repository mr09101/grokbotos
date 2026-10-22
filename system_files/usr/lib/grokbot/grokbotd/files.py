"""files.* : the user's home folder, nothing else.

Every path is relative to ~ (a leading "/" or "~/" is accepted and means
the same thing). Refused: anything that resolves outside ~ (.. or a
symlink), and any hidden component (".config", ".local", ...): that is
where grants, keys and app data live, so the files scope can never be
used to rewrite a permission file. Deletes go to the freedesktop trash.
"""
import base64
import datetime
import mimetypes
import os
import shutil
import urllib.parse

from .backends import BackendError

MAX_READ = 16 * 1024 * 1024
MAX_WRITE = 16 * 1024 * 1024
MAX_LIST = 2000


def home():
    return os.path.realpath(os.path.expanduser("~"))


def _rel(path):
    if not isinstance(path, str):
        raise BackendError("path must be a string")
    p = path.strip()
    if p.startswith("~"):
        p = p[1:]
    parts = [c for c in p.replace("\\", "/").split("/") if c not in ("", ".")]
    for c in parts:
        if c == "..":
            raise BackendError("'..' is not allowed")
        if c.startswith("."):
            raise BackendError("hidden files and folders are not available through the files scope")
        if "\x00" in c:
            raise BackendError("bad path")
    return parts


def resolve(path, must_exist=True):
    """Absolute path under ~ for an API path; checks symlinks too."""
    h = home()
    parts = _rel(path)
    full = os.path.join(h, *parts) if parts else h
    real = os.path.realpath(full)
    if real != h and not real.startswith(h + os.sep):
        raise BackendError("path leaves the home folder")
    if any(c.startswith(".") for c in os.path.relpath(real, h).split(os.sep) if c != "."):
        raise BackendError("hidden files and folders are not available through the files scope")
    if must_exist and not os.path.lexists(real):
        raise BackendError("no such file or folder: %s" % api_path(real))
    return real


def api_path(real):
    rel = os.path.relpath(real, home())
    return "/" if rel == "." else "/" + rel.replace(os.sep, "/")


def _entry(real, st=None):
    st = st or os.stat(real)
    is_dir = os.path.isdir(real)
    return {"name": os.path.basename(real) if api_path(real) != "/" else "~",
            "path": api_path(real), "type": "dir" if is_dir else "file",
            "size": 0 if is_dir else st.st_size, "mtime": int(st.st_mtime),
            "mime": None if is_dir else (mimetypes.guess_type(real)[0] or "application/octet-stream"),
            "writable": os.access(real, os.W_OK)}


def files_list(params):
    d = resolve(params.get("path", "/"))
    if not os.path.isdir(d):
        raise BackendError("not a folder")
    out, hidden = [], 0
    with os.scandir(d) as it:
        for e in it:
            if e.name.startswith("."):
                hidden += 1
                continue
            try:
                real = os.path.realpath(e.path)
                h = home()
                if real != h and not real.startswith(h + os.sep):
                    continue
                out.append(_entry(e.path, e.stat()))
            except OSError:
                continue
    out.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
    return {"path": api_path(d), "entries": out[:MAX_LIST], "truncated": len(out) > MAX_LIST,
            "hidden": hidden}


def files_stat(params):
    return _entry(resolve(params["path"]))


def files_read(params):
    f = resolve(params["path"])
    if os.path.isdir(f):
        raise BackendError("is a folder")
    size = os.path.getsize(f)
    if size > MAX_READ:
        raise BackendError("file is larger than %d MB" % (MAX_READ // 1048576))
    with open(f, "rb") as fh:
        data = fh.read()
    enc = params.get("encoding", "utf-8")
    if enc == "utf-8":
        try:
            return {"path": api_path(f), "encoding": "utf-8", "size": size, "data": data.decode("utf-8")}
        except UnicodeDecodeError:
            raise BackendError("not UTF-8 text; ask for encoding=base64")
    return {"path": api_path(f), "encoding": "base64", "size": size,
            "data": base64.b64encode(data).decode()}


def _parent_ok(target):
    parent = os.path.dirname(target)
    resolve(api_path(parent))
    if not os.path.isdir(parent):
        raise BackendError("parent folder does not exist")


def files_write(params):
    target = resolve(params["path"], must_exist=False)
    if target == home():
        raise BackendError("bad path")
    _parent_ok(target)
    if os.path.isdir(target):
        raise BackendError("is a folder")
    if os.path.exists(target) and not params.get("overwrite", False):
        raise BackendError("file exists; pass overwrite=true")
    if params.get("encoding", "utf-8") == "base64":
        try:
            data = base64.b64decode(params["data"], validate=True)
        except ValueError:
            raise BackendError("data is not base64")
    else:
        data = params["data"].encode("utf-8")
    if len(data) > MAX_WRITE:
        raise BackendError("too large")
    tmp = target + ".grokbot-tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, target)
    return _entry(target)


def files_mkdir(params):
    target = resolve(params["path"], must_exist=False)
    _parent_ok(target)
    if os.path.lexists(target):
        raise BackendError("already exists")
    os.mkdir(target)
    return _entry(target)


def files_move(params):
    src = resolve(params["path"])
    dst = resolve(params["to"], must_exist=False)
    if src == home() or dst == home():
        raise BackendError("bad path")
    _parent_ok(dst)
    if os.path.lexists(dst):
        raise BackendError("destination exists")
    if os.path.isdir(src) and (dst + os.sep).startswith(src + os.sep):
        raise BackendError("cannot move a folder into itself")
    os.rename(src, dst)
    return _entry(dst)


def _trash_dirs():
    base = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home(), ".local", "share"), "Trash")
    for d in ("files", "info"):
        os.makedirs(os.path.join(base, d), exist_ok=True)
    return base


def files_trash(params):
    src = resolve(params["path"])
    if src == home():
        raise BackendError("bad path")
    base = _trash_dirs()
    name = os.path.basename(src)
    cand, n = name, 1
    while os.path.lexists(os.path.join(base, "files", cand)) or \
            os.path.lexists(os.path.join(base, "info", cand + ".trashinfo")):
        n += 1
        cand = "%s.%d" % (name, n)
    with open(os.path.join(base, "info", cand + ".trashinfo"), "w") as fh:
        fh.write("[Trash Info]\nPath=%s\nDeletionDate=%s\n" % (
            urllib.parse.quote(src), datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    shutil.move(src, os.path.join(base, "files", cand))
    return {"path": api_path(src), "trashed": True}


METHODS = {
    "files.list": files_list,
    "files.stat": files_stat,
    "files.read": files_read,
    "files.write": files_write,
    "files.mkdir": files_mkdir,
    "files.move": files_move,
    "files.trash": files_trash,
}
