# 독과 단축키 / Docks & hotkeys

바탕화면에는 아이콘이 없다. 앱은 독, 런처, Grok Bot으로 연다. / There are no desktop icons. Open apps from the dock, the launcher or Grok Bot.

## 독 / Docks
- 위·아래 독은 아이콘만 표시 / top/bottom docks show icons only. 왼쪽·오른쪽 독은 아이콘만 또는 아이콘+이름 / left/right docks show icons, or icons plus labels.
- 기본은 아래 독, 아이콘만 / default: bottom dock, icons only.

```bash
grokbot-dock-config show
grokbot-dock-config set left labels   # 왼쪽 / left: 아이콘+이름 / icons + labels
grokbot-dock-config set bottom off
grokbot-dock-config icon-size 48
grokbot-dock-config status bottom   # 상태 영역 위치 / status area: auto|off|top|bottom|left|right
grokbot-dock-config reset
```

### 상태 영역 / Status area
독 끝에 Wi-Fi, 볼륨, 배터리, 시계가 보인다. Wi-Fi를 누르면 Wi-Fi 설정, 볼륨을 누르면 음소거, 볼륨 위에서 스크롤하면 조절. 마우스를 올리면 자세히 보인다. 배터리가 충전 중이면 "충전 중", 전원에 연결돼 있는데 방전 중이 아니면 "전원 연결됨", 가득 차면 "전원 연결됨 (가득 참)", 방전 중이면 잔량 퍼센트다. 아이콘만 있는 독에서도 그 문구는 배터리에 마우스를 올리면 보인다.
The end of the dock shows Wi-Fi, volume, battery and the clock. Click Wi-Fi for Wi-Fi setup, click volume to mute, scroll over it to adjust. Hover for details. While charging the battery reads "충전 중". Plugged in and not discharging it reads "전원 연결됨", and "전원 연결됨 (가득 참)" when full. While discharging it shows the percent remaining. Icon-only docks show the same words in the battery tooltip.

## 단축키 / Hotkeys

| 키 / Key | 동작 / Action |
|---|---|
| `Alt+Space`, `Super+Space` | 앱 런처 / app launcher |
| `Alt+G`, `Super+G` | Grok Bot으로 / back to Grok Bot |
| `Alt+Tab`, `Alt+Shift+Tab` | 창 전환 / switch windows |
| `Alt+F4`, `Super+Q` | 창 닫기 / close window |
| `Super+L`, `Alt+L` | 화면 잠금 / lock the screen ([잠금 / lock](lock-and-idle.md)) |
| `Super+Shift+N`, `Alt+Shift+N` | 방해 금지 켜기/끄기 / toggle Do Not Disturb |
| `Print` | 전체 화면 스크린샷 / full screenshot |
| `Shift+Print` | 영역 스크린샷 / region screenshot |
| `한/영`, `Shift+Space`, 오른쪽 `Alt` / Right Alt | 한글·영어 전환 / switch Korean–English ([한글 입력 / Korean input](korean-input.md)) |
| 볼륨 키 / volume keys, 음소거 / mute | 볼륨 조절, 화면에 막대 표시 / change volume with an on-screen bar |
| 밝기 키 / brightness keys | 화면 밝기 / screen brightness |
| 재생·다음·이전 / play, next, previous | 미디어 재생 제어 / media control (playerctl) |

자세한 구현은 / Details: [`docs/DOCK.md`](../docs/DOCK.md)
