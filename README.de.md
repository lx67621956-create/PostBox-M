# PostBox-M

**Einem anderen Rechner Arbeit geben, auch von unterwegs.**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Français](README.fr.md) · Deutsch · [Português](README.pt-BR.md)

Du bist unterwegs, nur ein Handy dabei. Du sagst dem Assistenten auf dem Handy: gib das dem Rechner zu Hause. Er tut es — an den Bürorechner in einer anderen Stadt, an die Maschine, die immer läuft, an den Desktop zu Hause. Der Rechner nimmt die Aufgabe, macht sie, behält die Datei lokal und schickt einen Lieferschein zurück: wo sie liegt, wie groß sie ist und ob sie passt.

Wie das unterwegs läuft, ist nicht deine Sorge. Ein Ordner, den mehrere Rechner sehen, reicht: Google Drive, ein privates Git-Repo, Syncthing, ein USB-Stick. Kein Server, keine Datenbank, kein Konto, kein VPN.

## Was du tatsächlich bekommst

**1. Leichtgewichtig.**
Das Postfach ist ein Ordner. Kein Dauerprozess, keine Datenbank, nichts, was man nachts überwachen muss. Ein paar KB Text – lesbar, kopierbar, komplett mitnehmbar.

**2. Kein Server zum Ausrollen.**
Kein Port, kein Konto, kein IT-Ticket, kein VPN. Ist der Ordner da, läuft das System; ist er weg, fällt auch nichts aus.

**3. Viele Agenten, eine Warteschlange.**
Mehrere Rechner und verschiedene KIs arbeiten dieselbe Warteschlange ab. Eine Aufgabe, ein Verantwortlicher: Übernehmen heißt eine Datei anzulegen, die es nicht gibt – sechs Agenten greifen zu, genau einer gewinnt, die anderen fünf gehen mit Code 3.

**4. Viele Speicher.**
Google Drive, privates Git, WebDAV, SSH, S3, lokaler Ordner, USB-Stick – sieben Backends, dieselben Befehle. Nimm, was du schon hast.

**5. Null Abhängigkeiten.**
Nur Python-Standardbibliothek, 3.9+. Nichts zu kompilieren, kein Lockfile, keine Supply Chain zu prüfen.

## Installation

```bash
pip install https://github.com/lx67621956-create/PostBox-M/releases/download/v0.4.0/postbox_m-0.4.0-py3-none-any.whl
```

Aus dem Quellcode: `git clone … && uv tool install .`

## Sechzig Sekunden

```bash
# Rechner A
postbox init --transport local --path "~/Dropbox/team-inbox" --agent alice
postbox new --to bob --title "wochenbericht" --ask "Fünf Punkte, nur Zahlen."

# Rechner B
postbox init --transport local --path "~/Dropbox/team-inbox" --agent bob
postbox inbox          # 1 Aufgabe, von alice
postbox ack <id>
postbox result <id> --artifact woche.md --text "Zahlen für KW 45, Quellen in der Datei"
```

Das ist die ganze Schleife. Der Rest — `watch`, `lint`, `doctor` — hält sie
unbeaufsichtigt am Laufen.

## Backend wählen

`postbox providers` zeigt jede Option mit einem fertigen Befehl:

| Preset | funktioniert in Festlandchina | was es ist |
|---|---|---|
| `git` | ja | ein privates Repo auf Gitee / GitHub / eigenem VPS; ein Commit pro Schreibvorgang |
| `local` | ja | jeder Ordner, den dein Sync-Tool ohnehin repliziert |
| `webdav` | ja | Nutstore, Nextcloud, Alist |
| `sftp` | ja | ein VPS, den du schon hast |
| `s3` | kommt darauf an | MinIO, Cloudflare R2, Aliyun OSS |
| `gdrive` | nein | Google Drive |
| `onedrive` / `dropbox` | nein | OneDrive, Dropbox |

`local` braucht kein rclone, kein OAuth, kein Konto und kein Netzwerk — zwei
Checkouts auf denselben Ordner sind ein funktionierendes Postfach, und genau so
läuft die Testsuite.

## Für die KI-Agenten

Eine Warteschlange funktioniert nur, wenn alle Agenten dieselben Regeln befolgen,
deshalb werden die Regeln mitgeliefert:

```bash
postbox instructions > AGENTS.md
```

Darin stehen die Schleife (vor der Arbeit bestätigen, Manifest im Ergebnis), die
harten Regeln (niemals die Datei eines anderen Agenten bearbeiten, niemals ein
Geheimnis schreiben) und die Bedeutung der Exit-Codes — welcher „du hast das Rennen
verloren" heißt und welcher „das Postfach ist nicht erreichbar". Einfügen in den
System-Prompt, `AGENTS.md`, `CLAUDE.md` oder eine Projekt-Skill.

## Kleingedrucktes

Zwei Dinge: Ein synchronisierter Ordner zeigt eine Datei erst, wenn der Client sie
ausgeliefert hat — also langsamer pollen als die Sync-Latenz. Und wenn zwei
Bearbeitungen kollidieren, legt der Desktop-Client `foo (1).md` neben `foo.md` an;
`lint` meldet das, und das Original bleibt unberührt, weil hier nichts an Ort und
Stelle umgeschrieben wird.

Tiefer: [`docs/protocol.md`](docs/protocol.md) (Spezifikation) und
[`docs/design-notes.md`](docs/design-notes.md) (warum es so gebaut ist).

## Über

Von **闷闷AI说** — KI-Nachrichten, auf Chinesisch, ohne Hype.

- YouTube: <https://www.youtube.com/@menmenAI>
- Bilibili: <https://space.bilibili.com/34234499>

MIT-Lizenz.
