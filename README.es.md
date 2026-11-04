# PostBox-M

**Una carpeta que tus agentes pueden compartir. Esa es toda la infraestructura.**

[English](README.md) · [中文](README.zh-CN.md) · Español · [日本語](README.ja.md) · [한국어](README.ko.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

Dos o más agentes de IA, en máquinas que no pueden comunicarse entre sí, trabajando una única cola compartida. Sin broker, sin servidor, sin base de datos, sin cuentas, sin VPN. Si tus agentes pueden leer y escribir una carpeta —Google Drive, un repositorio git privado, un par de Syncthing, un pendrive—, pueden pasarse trabajo entre ellos.

## Lo que realmente obtienes

**1. Nada que mantener en marcha.**
El buzón *es* una carpeta. No hay demonio que desplegar, ni puerto que abrir, ni token que rotar, ni broker que mantener vivo a las 3 de la mañana. Si la carpeta existe, el sistema está operativo. El coste de infraestructura del bus de mensajes es cero.

**2. Un solo dueño por tarea, garantizado por el sistema de archivos.**
Reclamar un trabajo es `create-if-absent`. Seis agentes compitiendo por la misma tarea: exactamente uno la obtiene, los otros cinco salen con código 3 y se retiran. El trabajo duplicado no se evita porque dos agentes "se pusieron de acuerdo", sino porque uno de ellos **no pudo físicamente crear el archivo**.

**3. Nada se sobrescribe nunca.**
Una tarea se escribe una vez y no se edita jamás. Cada acción —confirmar, anotar, entregar, bloquear— es un archivo nuevo con un nombre único. El historial de un trabajo queda completo por construcción, no por disciplina; y con el backend git, `git log` demuestra ante un tercero quién reclamó qué y cuándo.

**4. Sondear no cuesta nada cuando no ha pasado nada.**
`postbox watch` imprime una salida idéntica byte a byte mientras la carpeta no cambia y sale con 0. Un cron compara la salida —o simplemente el código de salida— y se salta por completo la llamada al modelo. Un agente inactivo cuesta cero tokens y solo despierta cuando hay algo nuevo de verdad.

**5. Una entrega es un archivo con hash, no una frase.**
`postbox result --artifact report.md` escribe archivo, carpeta, tamaño y sha256 en el recibo. "Hecho" dicho en un chat no es una entrega, y la herramienta no permite que un agente lo registre como tal.

**6. Funciona donde ya estás.**
Un repositorio privado en Gitee, una carpeta WebDAV de Nutstore, un VPS por SSH, Google Drive, dos portátiles en la misma LAN. Nadie necesita una cuenta de Google, nadie necesita una VPN, nadie necesita abrir un puerto entrante.

**7. Cero dependencias.**
Solo la biblioteca estándar de Python, Python 3.9+, un comando. Nada que compilar, sin lockfile, sin cadena de suministro que auditar.

## Instalación

```bash
pip install https://github.com/lx67621956-create/PostBox-M/releases/download/v0.4.0/postbox_m-0.4.0-py3-none-any.whl
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
