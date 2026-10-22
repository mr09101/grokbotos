#!/usr/bin/python3
"""Ask the user before grokbot-install installs a Flatpak (security review #9).

  flatpak_consent.py <app-id> <name> <caller-pid>   (stdin: app metadata)

stdin is `flatpak remote-info --show-metadata flathub <app-id>`. The
prompt names the caller (identified from its pid like grokbotd does), the
app, and every permission it asks for, marking the broad ones. It is a
power-class prompt: shown on every install, no "Always" and no "This
session". Exit 0 = the user allowed it once, 3 = denied or no answer.
"""
import configparser
import json
import os
import sys

sys.path.insert(0, os.environ.get("GROKBOT_PYLIB") or os.path.dirname(os.path.abspath(__file__)))

from grokbotd import consent, peer  # noqa: E402

# Permissions that let an app out of its sandbox, or close to it.
BROAD = {
    ("filesystems", "host"): "모든 파일 / all files on the computer",
    ("filesystems", "host-os"): "시스템 파일 / system files",
    ("filesystems", "host-etc"): "시스템 설정 / system settings (/etc)",
    ("filesystems", "home"): "홈 폴더 전체 / the whole home folder",
    ("devices", "all"): "모든 장치(카메라, USB 등) / all devices (camera, USB, ...)",
    ("sockets", "x11"): "X11 화면(다른 창 엿보기 가능) / X11 display (can watch other windows)",
    ("sockets", "system-bus"): "시스템 버스 / system D-Bus",
    ("sockets", "session-bus"): "세션 버스 전체 / the whole session D-Bus",
    ("talk", "org.freedesktop.Flatpak"): "샌드박스 밖에서 명령 실행 / run commands outside the sandbox",
}


def permissions(metadata):
    """[(text, broad)] from a Flatpak metadata file."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        cp.read_string(metadata)
    except configparser.Error:
        return [("권한 정보를 읽지 못함 / could not read the permissions", True)]
    out = []
    if cp.has_section("Context"):
        for key, val in cp.items("Context"):
            for v in [x for x in val.split(";") if x]:
                base = v.split(":", 1)[0].lstrip("!")
                broad = BROAD.get((key, base))
                out.append(("%s=%s%s" % (key, v, " — " + broad if broad else ""), bool(broad) and not v.startswith("!")))
    for sec in ("Session Bus Policy", "System Bus Policy"):
        if cp.has_section(sec):
            for name, mode in cp.items(sec):
                broad = BROAD.get(("talk", name))
                out.append(("%s: %s %s%s" % (sec, mode, name, " — " + broad if broad else ""), bool(broad)))
    return out or [("추가 권한 없음 / no extra permissions", False)]


def main():
    app_id, name, pid = sys.argv[1], sys.argv[2], int(sys.argv[3])
    perms_list = permissions(sys.stdin.read())
    principal, _ = peer.identify(pid, os.getuid())
    broad = [t for t, b in perms_list if b]
    warning = None
    if broad:
        warning = ["이 앱은 샌드박스 밖까지 닿는 권한을 요청합니다: " + "; ".join(broad),
                   "This app asks for permissions that reach outside its sandbox: " + "; ".join(broad)]
    ans, detail = consent.prompt(
        principal, None, "apps", "flatpak.install",
        ["Flathub 앱 설치: %s (%s)" % (name, app_id), "Install Flathub app: %s (%s)" % (name, app_id)],
        {"app": app_id, "permissions": [t for t, _ in perms_list]},
        allow_always=False, allow_session=False, warning=warning)
    print(json.dumps({"answer": ans, "detail": detail, "principal": principal, "permissions": perms_list},
                     ensure_ascii=False), file=sys.stderr)
    sys.exit(0 if ans == "once" else 3)


if __name__ == "__main__":
    main()
