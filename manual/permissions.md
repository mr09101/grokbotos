# 권한과 동의 / Permissions and consent

Grok Bot OS에서 앱과 Grok Bot은 OS 기능을 grokbotd API로만 쓴다. 권한은 **앱 단위가 아니라 기능(scope) 단위**다. 소리, 화면 밝기, 네트워크, 전원, 키보드, 알림, 파일, 카메라, 마이크, 위치 같은 기능마다 따로 정한다.
Apps and Grok Bot use OS functions only through the grokbotd API. Permissions are **per function (scope), not per app**: sound, display, network, power, keyboard, notifications, files, camera, microphone, location and so on, each on its own.

## 모드 / Modes

| 모드 / Mode | 뜻 / Meaning |
|---|---|
| 허용 / allow | 묻지 않고 실행 / runs without asking |
| 묻기 / ask | 쓸 때마다 동의 창 / a consent prompt each time |
| 거부 / deny | 실행 안 함 / refused |

처음에 웹 앱은 아무 권한도 없다. 웹 앱이 권한을 요청하면 동의 창이 뜬다.
A web app starts with nothing. When it asks for a function, a consent prompt appears.

## 동의 창 / The consent prompt

창에는 **누가**(웹 앱 주소, 또는 "이 컴퓨터의 프로그램"), **무엇을**(기능), **어떤 동작**(예: 볼륨 40%)이 나온다.
It shows **who** (the web app's address, or "a program on this computer"), **what** (the function) and **which action** (for example volume 40%).

- **거부 / Deny** (기본, `Esc`): 이번 호출을 막는다. / blocks this call.
- **한 번 허용 / Allow once**: 이번 한 번만. / just this once.
- **항상 허용 / Always allow**: 이 호출자에게 이 기능을 계속 허용. 설정 앱의 권한 페이지에서 취소할 수 있다. / keeps allowing; revoke it in Settings → Permissions.

60초 안에 답하지 않으면 거부로 처리한다. / No answer in 60 seconds counts as Deny.

**카메라, 마이크, 전원(절전·다시 시작·끄기)** 은 매번 묻고 "항상 허용"이 없다. 카메라나 마이크를 쓰는 동안 독의 상태 칸에 빨간 표시가 뜬다. 마우스를 올리면 누가 쓰는지 보인다.
**Camera, microphone and power (suspend, restart, shut down)** always ask and have no Always button. While the camera or microphone is in use, a red indicator shows in the dock status area; hover it to see who.

## 이 컴퓨터의 프로그램 / Programs on this computer

터미널, Grok Bot, MCP 도구처럼 내 계정으로 실행된 프로그램은 정보를 읽을 수 있고, 소리·밝기·알림·한글 입력·잠금 시간은 바로 바꿀 수 있다. 네트워크, 화면 캡처, 전원, 카메라, 마이크는 묻는다. 기본값은 `/etc/grokbot/api-permissions.json`의 `local`에 있다.
Programs running as you (terminal, Grok Bot, MCP tools) can read status and change sound, brightness, notifications, input and idle times directly. Network, screen capture, power, camera and microphone ask. Defaults: `local` in `/etc/grokbot/api-permissions.json`.

"항상 허용"은 그 프로그램 하나에만 적용된다. grokbotd는 프로그램이 밝힌 이름이 아니라 커널이 알려 주는 프로세스로 신원을 정한다(systemd 유닛, 또는 실행 파일과 스크립트). 내 신원 보기: `grokbot-os whoami`.
"Always allow" applies to that one program. grokbotd identifies it from the kernel (its systemd unit, or its executable and script), not from the name it gives. See yours with `grokbot-os whoami`. Grant a unit from the CLI with `grokbot-os grant unit:NAME.service audio ask`.

## 보기와 취소 / View and revoke

```
grokbot-os grants                                  # 호출자별 기능 모드 / modes per caller
grokbot-os revoke http://notes.app.localhost:7311  # 모든 기능 취소 / revoke all
grokbot-os revoke http://notes.app.localhost:7311 audio
grokbot-os grant http://notes.app.localhost:7311 audio ask   # 확인 창이 뜬다 / asks you
grokbot-os audit                                   # 최근 호출 / recent calls
grokbot-os audit decision=deny
```

모든 호출(허용, 거부, 실패)은 감사 기록 `~/.local/state/grokbot/audit.jsonl`에 남는다. 비밀번호는 기록되지 않는다.
Every call (allowed, denied or failed) is written to the audit log `~/.local/state/grokbot/audit.jsonl`. Passwords are never logged.

보안 모델과 알려진 한계는 [SECURITY.md](../SECURITY.md#권한-모델과-위협-모델--permission-and-threat-model)에 있다. / The security model and known limitations are in SECURITY.md.
