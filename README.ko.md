# PostBox-M

**밖에 있어도 다른 컴퓨터에 일을 맡길 수 있습니다.**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · [日本語](README.ja.md) · 한국어 · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

밖에 있고 손에는 휴대폰만 있습니다. 휴대폰의 어시스턴트에게 말합니다: 이건 집 컴퓨터에 넘겨. 그러면 다른 도시의 회사 컴퓨터로, 늘 켜져 있는 서버로, 집 데스크톱으로 넘어갑니다. 받은 컴퓨터가 알아서 하고, 파일은 그 자리에 두고, 어디에 있는지·얼마나 큰지·맞는지를 적은 전표를 돌려줍니다.

중간에 어떻게 갔는지는 몰라도 됩니다. 여러 대가 볼 수 있는 폴더 하나면 충분합니다. Google Drive, 프라이빗 git, Syncthing, USB 메모리. 서버도, 데이터베이스도, 계정도, VPN도 필요 없습니다.

## 실제로 얻는 것

**1. 가볍습니다.**
메일박스는 폴더 하나입니다. 상주 프로세스도, 데이터베이스도, 새벽에 지켜볼 것도 없습니다. 안에는 몇 KB의 텍스트뿐이라 열어 보고 통째로 복사할 수 있습니다.

**2. 서버를 배포할 필요가 없습니다.**
포트를 열지 않고, 계정을 만들지 않고, IT 승인도 VPN도 필요 없습니다. 폴더가 있으면 시스템이 살아 있고, 없어도 무너질 것이 없습니다.

**3. 여러 에이전트, 하나의 큐.**
여러 대의 기기와 서로 다른 AI가 같은 큐에서 일합니다. 작업의 담당자는 하나: 수락은 없는 파일을 만드는 일이라 여섯이 동시에 달려도 하나만 성공하고 나머지는 코드 3으로 물러납니다.

**4. 저장 방식은 골라 씁니다.**
Google Drive, 프라이빗 git, WebDAV, SSH, S3, 로컬 폴더, USB 메모리까지 7가지 백엔드, 명령은 동일합니다. 가진 것을 쓰면 됩니다.

**5. 의존성 0.**
Python 표준 라이브러리만, 3.9 이상, 명령 하나. 빌드도 lockfile도 감사할 공급망도 없습니다.

## 설치

```bash
pip install https://github.com/lx67621956-create/PostBox-M/releases/download/v0.4.0/postbox_m-0.4.0-py3-none-any.whl
```

소스에서 설치: `git clone … && uv tool install .`

## 60초 안에 돌려보기

```bash
# 머신 A
postbox init --transport local --path "~/Dropbox/team-inbox" --agent alice
postbox new --to bob --title "주간 리포트" --ask "핵심 다섯 개, 숫자만."

# 머신 B
postbox init --transport local --path "~/Dropbox/team-inbox" --agent bob
postbox inbox          # 작업 1개, alice가 보냄
postbox ack <id>
postbox result <id> --artifact weekly.md --text "45주차 숫자, 출처는 파일 안에"
```

루프는 이게 전부입니다. 나머지 `watch`·`lint`·`doctor`는 무인으로 계속 돌리기 위한 장치입니다.

## 백엔드 고르기

`postbox providers`가 모든 선택지와 실행 가능한 명령을 보여줍니다:

| 프리셋 | 중국 본토 사용 가능 | 무엇인가 |
|---|---|---|
| `git` | 예 | Gitee / GitHub / 자기 VPS의 프라이빗 저장소, 쓰기 1회당 커밋 1개 |
| `local` | 예 | 기존 동기화 도구가 이미 복제하는 아무 폴더 |
| `webdav` | 예 | Nutstore, Nextcloud, Alist |
| `sftp` | 예 | 이미 가진 VPS |
| `s3` | 경우에 따라 | MinIO, Cloudflare R2, Aliyun OSS |
| `gdrive` | 아니오 | Google Drive |
| `onedrive` / `dropbox` | 아니오 | OneDrive, Dropbox |

`local`은 rclone도 OAuth도 계정도 네트워크도 필요 없습니다. 같은 폴더를 가리키는 두 개의 체크아웃이 곧 동작하는 메일박스이며, 테스트 스위트도 그렇게 돌아갑니다.

## AI 에이전트를 위해

큐가 작동하려면 모든 에이전트가 같은 규칙을 따라야 하므로, 규칙도 도구와 함께 배포합니다:

```bash
postbox instructions > AGENTS.md
```

루프(작업 전에 선점, 결과에는 매니페스트), 단단한 규칙(남의 파일을 편집하지 않는다, 비밀을 쓰지 않는다), 그리고 종료 코드의 의미 — 어느 것이 "경쟁에서 졌다"이고 어느 것이 "메일박스에 닿지 않는다"인지 — 를 담고 있습니다. 시스템 프롬프트, `AGENTS.md`, `CLAUDE.md`, 프로젝트 스킬 어디에 붙여도 됩니다.

## 작은 단서

두 가지만: 동기화 폴더는 클라이언트가 실제로 전달한 뒤에야 파일이 보이므로 폴링 간격을 동기화 지연보다 길게 두세요. 그리고 두 편집이 충돌하면 데스크톱 클라이언트가 `foo.md` 옆에 `foo (1).md`를 만듭니다 — `lint`가 보고하고, 원본은 그대로입니다. 이 시스템은 어떤 것도 제자리에서 덮어쓰지 않기 때문입니다.

더 깊은 내용: [`docs/protocol.md`](docs/protocol.md)(규격), [`docs/design-notes.md`](docs/design-notes.md)(설계 이유).

## 만든 사람

**闷闷AI说** — 과장 없이 전하는 중국어 AI 뉴스.

- YouTube: <https://www.youtube.com/@menmenAI>
- Bilibili: <https://space.bilibili.com/34234499>

MIT 라이선스.
