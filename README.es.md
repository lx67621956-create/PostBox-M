# PostBox-M

**Dale trabajo a otra computadora aunque no estés cerca.**

[English](README.md) · [中文](README.zh-CN.md) · Español · [日本語](README.ja.md) · [한국어](README.ko.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

Estás fuera, con el teléfono en la mano. Le dices al asistente del móvil: pásale esto a la máquina de casa. Y lo hace: a la computadora de la oficina en otra ciudad, al servidor que siempre está encendido, a la de casa. Esa máquina recoge la tarea, la hace, deja el archivo donde está y devuelve un recibo con dónde vive, cuánto pesa y si coincide.

Cómo viaja no es tu problema. Basta con una carpeta que varias máquinas puedan ver: Google Drive, un repo git privado, Syncthing, un pendrive. Sin servidor, sin base de datos, sin cuentas, sin VPN.

## Lo que realmente obtienes

**1. Ligero.**
El buzón es una carpeta. Sin proceso residente, sin base de datos, nada que vigilar de madrugada. Unos pocos KB de texto que puedes abrir, leer y llevarte entero.

**2. Sin servidor que desplegar.**
No abres puertos, no creas cuentas, no esperas permisos de TI, no necesitas VPN. Si la carpeta está, el sistema está; si no está, tampoco se cae nada.

**3. Varios agentes, una cola.**
Varias máquinas y varios AI distintos trabajan la misma cola. Una tarea, un responsable: reclamar es crear un archivo que no existe; seis agentes compiten y exactamente uno gana, los otros cinco salen con código 3.

**4. Varios almacenamientos.**
Google Drive, git privado, WebDAV, SSH, S3, carpeta local, pendrive: siete backends, los mismos comandos. Usa el que ya tengas.

**5. Cero dependencias.**
Solo la biblioteca estándar de Python, 3.9+. Nada que compilar, sin lockfile, sin cadena de suministro que auditar.

## Instalación

```bash
pip install "git+https://github.com/lx67621956-create/PostBox-M.git"
```

Desde el código: `git clone … && uv tool install .`

## Sesenta segundos

```bash
# máquina A
postbox init --transport local --path "~/Dropbox/buzon-equipo" --agent alice
postbox new --to bob --title "informe semanal" --ask "Cinco puntos, solo cifras."

# máquina B
postbox init --transport local --path "~/Dropbox/buzon-equipo" --agent bob
postbox inbox          # 1 tarea, de alice
postbox ack <id>
postbox result <id> --artifact semanal.md --text "Cifras de la semana 45, fuentes en el archivo"
```

Ese es todo el ciclo. El resto —`watch`, `lint`, `doctor`— existe para que siga funcionando sin supervisión.

## Elige un backend

`postbox providers` muestra todas las opciones con un comando listo para usar:

| preset | funciona en China continental | qué es |
|---|---|---|
| `git` | sí | un repositorio privado en Gitee / GitHub / tu VPS; un commit por escritura |
| `local` | sí | cualquier carpeta que tu herramienta de sincronización ya replique |
| `webdav` | sí | Nutstore, Nextcloud, Alist |
| `sftp` | sí | un VPS que ya tengas |
| `s3` | depende | MinIO, Cloudflare R2, Aliyun OSS |
| `gdrive` | no | Google Drive |
| `onedrive` / `dropbox` | no | OneDrive, Dropbox |

`local` no necesita rclone, ni OAuth, ni cuenta, ni red: dos checkouts apuntando a la misma carpeta ya son un buzón funcional, que es exactamente como corre la suite de pruebas.

## Para los agentes de IA

Una cola solo funciona si todos los agentes respetan las mismas reglas, así que las reglas se distribuyen con la herramienta:

```bash
postbox instructions > AGENTS.md
```

Define el ciclo (confirmar antes de trabajar, manifiesto en el resultado), las reglas duras (nunca editar el archivo de otro agente, nunca escribir un secreto) y qué significa cada código de salida: cuál es "perdiste la carrera" y cuál es "el buzón no responde". Pégalo en el prompt del sistema, en `AGENTS.md`, en `CLAUDE.md` o en la skill del proyecto.

## Letra pequeña

Dos cosas que conviene saber: una carpeta sincronizada solo muestra un archivo cuando el cliente lo ha entregado, así que sondea más lento que tu latencia de sincronización; y cuando dos ediciones chocan, el cliente de escritorio escribe `foo (1).md` junto a `foo.md` — `lint` lo reporta, y el original queda intacto porque en este sistema nada se reescribe en el sitio.

Más detalle: [`docs/protocol.md`](docs/protocol.md) (la especificación) y [`docs/design-notes.md`](docs/design-notes.md) (por qué está construido así).

## Acerca de

Hecho por **闷闷AI说** — noticias de IA, en chino, sin hype.

- YouTube: <https://www.youtube.com/@menmenAI>
- Bilibili: <https://space.bilibili.com/34234499>

Licencia MIT.
