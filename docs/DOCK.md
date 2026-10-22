# 독(Dock)

Grok Bot OS에는 **바탕화면 아이콘이 없다.** 앱으로 가는 길은 화면 가장자리의 독, `Alt+Space` 런처(fuzzel), 그리고 Grok Bot 자신이다.

## 동작

- 독은 화면 위·아래·왼쪽·오른쪽 어디에나, 여러 개를 동시에 둘 수 있다. 각 독은 layer-shell 패널이고 exclusive zone을 잡아서 창이 독 밑으로 들어가지 않는다.
- 위·아래 독은 **아이콘만** 보여 준다. 왼쪽·오른쪽 독은 **아이콘만** 또는 **아이콘+이름**(Grok Bot 앱의 봇 목록 사이드바처럼) 중 고른다.
- 첫 칸은 항상 Grok Bot이다. 그 뒤는 설치된 앱 이름순이다. 목록은 `.desktop` 파일에서 온다: `/usr/share/applications`, Flatpak exports(`~/.local/share/flatpak/exports`, `/var/lib/flatpak/exports`), `grokbot-install local`이 만드는 `~/.local/share/applications`. 앱을 설치하거나 지우면 독이 다시 그린다.
- 실행 중인 앱은 아이콘 옆(위·아래 독은 아래)에 파란 점, 보고 있는 앱은 밝은 배경으로 표시한다.
- 클릭: 실행 중이면 그 창으로 가고, 아니면 새 작업 공간에서 실행한다.

## 창 배치

전체화면을 쓰지 않는다. 전체화면 창은 독을 덮기 때문이다. 대신:

- Grok Bot은 항상 작업 공간 1에 있다 (`assign [app_id="grok-bot"]`). 부팅 후 첫 화면이고 기본 앱이다.
- 다른 앱은 독이나 런처에서 실행할 때 비어 있는 새 작업 공간에 열린다(`grokbot-run`). 작업 공간에 창이 하나뿐이라 독을 뺀 영역을 꽉 채운다(최대화).
- Grok Bot 래퍼는 더 이상 `--start-fullscreen`을 넘기지 않는다.

## 키

| 키 | 동작 |
|---|---|
| `Alt+Space`, `Super+Space` | 앱 런처 |
| `Alt+G`, `Super+G` | Grok Bot으로 돌아가기 |
| `Alt+Tab`, `Alt+Shift+Tab` | 모든 작업 공간의 창을 순서대로 전환 (`grokbot-alttab.py`) |
| `Alt+F4`, `Super+Q` | 보고 있는 창 닫기 (Grok Bot은 grokbot-kiosk가 다시 띄운다) |

## 설정

기본값은 `/etc/grokbot/dock.conf`, 사용자 값은 `~/.config/grokbot/dock.conf`. 기본은 **아래 독, 아이콘만**.

```ini
[dock]
top = off          # off | icons
bottom = icons     # off | icons
left = off         # off | icons | labels
right = off        # off | icons | labels
icon_size = 40     # 16-96
hide = footclient.desktop;foot-server.desktop
```

Grok Bot이나 사용자가 바꿀 때는 `grokbot-dock-config`를 쓴다. 파일을 쓰고 실행 중인 독에 SIGHUP을 보내 바로 반영한다.

```bash
grokbot-dock-config show
grokbot-dock-config set left labels     # 왼쪽 독: 아이콘+이름
grokbot-dock-config set right icons     # 오른쪽 독: 아이콘만
grokbot-dock-config set top icons
grokbot-dock-config set bottom off
grokbot-dock-config icon-size 48
grokbot-dock-config reset               # 사용자 설정 삭제, 기본값으로
```

`top`/`bottom`에 `labels`를 주면 거부한다.

## 구현

- `/usr/lib/grokbot/grokbot-dock.py`: Python + GTK3 + gtk-layer-shell(Fedora 패키지 `python3-gobject`, `gtk3`, `gtk-layer-shell`). 한 프로세스가 켜진 가장자리마다 창 하나를 만든다. 실행 상태는 1.5초마다 `swaymsg -t get_tree`로 읽는다.
- `/usr/local/bin/grokbot-dock`: sway가 시작할 때 실행, 죽으면 다시 띄움. 로그는 `~/.local/share/grokbot/dock.log`.
- waybar(작업 표시줄)와 nwg-dock은 Fedora에 있지만, 가장자리별로 "아이콘+이름" 모드를 고르는 요구를 맞추지 못해 쓰지 않았다.

## 확인

2026-10-21 로컬 VM(TCG)에서 확인: 기본 아래 독, 네 독 동시, 왼쪽 아이콘+이름/아이콘만 전환, 독 클릭으로 Foot 실행, 실행 표시 점, `Alt+Tab`, `Alt+G`. 실제 하드웨어, HiDPI, 여러 모니터는 확인하지 않았다.

## Grok Bot 창 안의 최소화/최대화/닫기 버튼

이 버튼들은 Grok Bot 앱이 자기 창 안에 직접 그린다. 창 관리자(sway)가 붙이는 장식이 아니라서 OS 설정으로는 없앨 수 없다.

- 앱을 전체화면으로 두면 버튼이 사라지지만, 그러면 독이 가려진다. 독과 함께 쓰는 지금 배치에서는 버튼이 남는다.
- sway에서 최소화와 최대화 버튼은 효과가 거의 없다. 닫기를 누르면 앱이 끝나고, grokbot-kiosk가 1초 뒤에 다시 띄운다.
- 근본 해결은 앱 쪽에 Linux 키오스크 옵션을 요청하는 것이다.

## 상태 영역 / Status area

독 하나의 끝(위·아래 독은 오른쪽 끝, 왼쪽·오른쪽 독은 아래 끝)에 Wi-Fi, 볼륨, 배터리, 시계를 둔다. 데이터는 grokbotd(`network.status`, `audio.status`, `power.status`)에서 5초마다 읽는다. 독도 OS API 클라이언트다. 구현은 `/usr/lib/grokbot/grokbot_status.py`(GTK 없음, 단위 테스트 있음).

- `status = auto`(기본): 아래 독, 없으면 켜진 첫 독. `off`이면 숨김. 특정 가장자리를 고르면 그 독이 꺼져 있을 때 표시하지 않는다(새 독을 만들지 않음).
- 위·아래 독과 왼쪽·오른쪽 `icons` 독은 아이콘만(시계는 숫자). 왼쪽·오른쪽 `labels` 독은 아이콘+글자.
- 클릭: Wi-Fi → `grokbot-wifi`, 볼륨 → 음소거, 볼륨 위에서 스크롤 → 조절. 마우스를 올리면 자세한 내용.
- 배터리: `Discharging`이면 AC여도 잔량 아이콘과 퍼센트. `Charging`일 때만 충전 아이콘과 "충전 중". AC이고 `Charging`/`Discharging`이 아니면(Unknown, 빈 상태, `Not charging`) 플러그 아이콘(`ac-adapter-symbolic`)과 "전원 연결됨". AC이고 `Full`이면 `battery-level-100-charged-symbolic`과 "전원 연결됨 (가득 참)". 위·아래 독은 아이콘만 보이므로, 그 문구는 모든 독의 배터리 버튼 툴팁에도 있다.
