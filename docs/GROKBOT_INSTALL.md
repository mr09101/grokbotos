# `grokbot-install` 규격

Grok Bot이 이 PC에 앱을 추가할 때 호출하는 명령이다. root로 실행하면 거부한다. 임의 URL을 받아 받지 않는다. 셸 문자열을 eval하지 않는다.

구현: `/usr/local/bin/grokbot-install`.

Grok Bot 0.71.2 RPM은 기본 이미지 빌드에 들어간다. 이 명령은 그 앱이 부를 수 있게 규격만 고정한 것이다. 앱이 이 명령을 실제로 부르는지, 다른 IPC를 요구하는지는 확인하지 않았다. 다른 IPC가 필요하면 그 앞에 얇은 어댑터를 두고, 이 명령의 의미는 바꾸지 않는다.

## 호출

```text
grokbot-install [--json] flatpak <app-id> [--name <이름>]
grokbot-install [--json] local --id <id> --name <이름> --source <경로> [--exec <상대경로>]
grokbot-install [--json] list
grokbot-install [--json] remove <id>
```

종료 코드:

| 코드 | 의미 |
|---|---|
| 0 | 성공 |
| 2 | 사용법, 검증 실패, 이미 설치됨, 없음 |
| 1 | flatpak 실패, root, 그 외 실행 오류 |

`--json`이면 stdout에 한 줄 JSON. 사람이 읽을 메시지는 stderr다. JSON의 `error` 값은 영어 토큰이다.

성공:

```json
{"ok":true,"id":"org.example.App","kind":"flatpak","name":"예시"}
```

실패:

```json
{"ok":false,"error":"invalid_app_id","message":"..."}
```

`list --json`은 객체 배열이다. 설치된 것이 없으면 `[]`.

`remove --json`:

```json
{"ok":true,"id":"hello","kind":"local","removed":true}
```

## flatpak

```text
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-info --user --show-metadata flathub <app-id>   # 요청 권한 읽기
(확인 창 / consent prompt)
flatpak install --user -y flathub <app-id>
```

**설치 전 확인(보안 리뷰 #9).** 설치할 때마다 동의 창이 뜬다. 누가 요청했는지(호출 프로세스, grokbotd와 같은 방식으로 식별), 앱 id·이름, 앱이 요청하는 권한 전체(`[Context]`, D-Bus 정책)를 보여 주고, 샌드박스 밖으로 닿는 권한(`filesystems=host`/`home`, `devices=all`, `sockets=x11`/`system-bus`/`session-bus`, `org.freedesktop.Flatpak` talk)은 경고로 강조한다. 전원 수준 프롬프트라 "항상 허용"과 "이번 세션"이 없고, 거부·무응답(60초)·화면 없음은 설치하지 않음(종료 코드 3, `"error":"denied"`). `-y`는 flatpak 자신의 질문에만 답한다. 한계: 같은 uid 프로그램은 `flatpak`을 직접 부를 수 있으므로, 이 확인은 Grok Bot이 `grokbot-install`을 쓰는 경로를 지킨다(SECURITY.md 1번). 이후 앱 업데이트가 권한을 늘리는 것은 flatpak의 기본 동작을 따른다.

앱 id는 `org.example.App` 형태만 받는다. 원격 이름은 `flathub`만. 다른 리모트, ref URL, `.flatpak` 경로는 이 명령으로 설치할 수 없다.

설치 기록은 `~/.local/share/grokbot/installed/<app-id>.json`이다. Flatpak이 제공하는 `.desktop`을 덮어쓰지 않는다. fuzzel은 `XDG_DATA_DIRS`의 Flatpak export 경로에서 그 데스크톱 파일을 본다. `grokbot-session`이 그 변수를 넣고 sway를 실행한다.

제거는 `flatpak uninstall --user -y <app-id>` 뒤 기록 파일을 지운다.

네트워크가 없으면 설치는 실패하고, 기록 파일은 만들지 않는다. 첫 부팅에 리모트를 추가하지 못해도 키오스크는 뜬다. 다음 `grokbot-install flatpak`이 다시 추가를 시도한다.

## local

Grok Bot이 이미 디스크에 만들어 둔 파일이나 디렉터리를 사용자 홈으로 복사한다.

```text
~/Apps/<id>/
~/.local/share/applications/grokbot-local-<id>.desktop
~/.local/share/grokbot/installed/<id>.json
```

`<id>`는 `^[a-z][a-z0-9._-]{0,62}$`다.

`--source`가 파일이면 `~/Apps/<id>/<id>`로 복사하고 실행 비트를 켠다. `--exec`는 받으면 거부한다.

`--source`가 디렉터리이면 `--exec`가 필수다. 상대 경로만 허용한다. `..`, 절대 경로, 공백은 거부한다. 복사 뒤 그 파일이 디렉터리 안의 일반 파일이 아니면 설치를 롤백한다.

심볼릭 링크인 소스, 또는 디렉터리 안의 심볼릭 링크는 거부한다.

이미 같은 id가 있으면 거부한다. `remove` 뒤에 다시 설치한다.

데스크톱 파일의 `Exec`는 홈 안의 절대 경로다. `HOME`에 공백이나 따옴표가 있으면 명령 전체가 거부된다. `grokbot` 홈(`/var/home/grokbot`)은 해당하지 않는다.

## 앱 전환

| 키 | 프로그램 | 동작 |
|---|---|---|
| `Super+Space`, `Alt+Space` | `grokbot-switch` | fuzzel. layer-shell이라 전체화면 규칙에 가리지 않는다 |
| `Super+G`, `Alt+G` | `grokbot-focus` | `GROKBOT_APP_ID` 창에 포커스. 네이티브 기본값은 `grok-bot`. 플레이스홀더 빌드만 `firefox` |
| `Alt+Tab` | sway | 다음 창 |
| `Alt+F4` | sway | 보고 있는 창 닫기 |

Grok Bot 자신은 `grokbot-kiosk`가 다시 띄운다. Alt+F4로 닫혀도 1초 뒤 돌아온다.

배포판 Firefox 런처는 `~/.local/share/applications/firefox.desktop`에서 숨긴다. 키오스크 Firefox와 같은 창을 다투지 않게 하기 위해서다.

## 아직 하지 않는 것

로컬 앱은 `grokbot` 사용자 권한으로 실행된다. 파일시스템 격리, 네트워크 차단, 장치 차단은 없다. Flatpak으로 설치한 앱만 Flatpak 샌드박스를 탄다. 이 차이는 Phase D에서 다룬다. 지금 헬퍼를 샌드박스라고 보면 안 된다.

이 명령은 앱을 실행하지 않는다. 복사하고 데스크톱 파일만 쓴다. 실행은 fuzzel 또는 사용자가 고른 런처가 한다.
