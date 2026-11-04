# PostBox-M

**Ein Ordner, den deine Agenten teilen. Das ist die gesamte Infrastruktur.**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Français](README.fr.md) · Deutsch · [Português](README.pt-BR.md)

Zwei oder mehr KI-Agenten auf Rechnern, die sich nicht erreichen können, arbeiten
eine gemeinsame Warteschlange ab. Kein Broker, kein Server, keine Datenbank, kein
Konto, kein VPN. Wenn deine Agenten einen Ordner lesen und schreiben können —
Google Drive, ein privates Git-Repo, ein Syncthing-Paar, ein USB-Stick —, können
sie einander Arbeit übergeben.

## Was du tatsächlich bekommst

**1. Nichts, was laufen muss.**
Das Postfach *ist* ein Ordner. Kein Daemon zu deployen, kein Port zu öffnen, kein
Token zu rotieren, kein Broker, der um 3 Uhr nachts am Leben gehalten werden muss.
Existiert der Ordner, läuft das System. Die Infrastrukturrechnung für den
Message-Bus ist null.

**2. Ein Besitzer pro Aufgabe, erzwungen vom Dateisystem.**
Eine Aufgabe übernehmen heißt `create-if-absent`. Sechs Agenten jagen dieselbe
Aufgabe: genau einer bekommt sie, die anderen fünf enden mit Code 3 und treten
zurück. Doppelarbeit hört auf, weil ein Agent die Datei **physisch nicht anlegen
konnte** — nicht, weil sich zwei Agenten „geeinigt" haben.

**3. Nichts wird je überschrieben.**
Eine Aufgabe wird einmal geschrieben und nie bearbeitet. Jede Aktion — Bestätigung,
Notiz, Ergebnis, Blocker — ist eine neue Datei mit eindeutigem Namen. Die
Geschichte einer Aufgabe ist damit strukturell vollständig, nicht durch Disziplin.
Und mit dem Git-Backend beweist `git log` einem Dritten, wer wann was übernommen hat.

**4. Polling kostet nichts, wenn nichts passiert ist.**
`postbox watch` gibt byte-identische Ausgabe aus, solange der Ordner unverändert
ist, und endet mit 0. Ein Cronjob vergleicht die Ausgabe — oder nur den Exit-Code —
und überspringt den Modellaufruf komplett. Ein untätiger Agent kostet null Token
und wacht nur auf, wenn es wirklich etwas Neues gibt.

**5. Eine Lieferung ist eine Datei mit Hash, kein Satz.**
`postbox result --artifact report.md` schreibt Datei, Ordner, Größe und sha256 in
die Quittung. „Erledigt" im Chat ist keine Lieferung, und das Werkzeug lässt keinen
Agenten sie als solche eintragen.

**6. Läuft dort, wo du schon bist.**
Ein privates Repo auf Gitee, ein Nutstore-WebDAV-Ordner, ein VPS per SSH, Google
Drive, zwei Laptops im selben LAN. Niemand braucht ein Google-Konto, niemand ein
VPN, niemand einen eingehenden Port.

**7. Null Abhängigkeiten.**
Nur die Python-Standardbibliothek, Python 3.9+, ein Befehl. Nichts zu kompilieren,
kein Lockfile, keine Lieferkette zu prüfen.

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
