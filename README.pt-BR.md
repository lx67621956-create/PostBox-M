# PostBox-M

**Dar trabalho a outro computador, mesmo de longe.**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · Português

Você está na rua, só com o celular. Diz ao assistente do celular: passa isso para a máquina de casa. E ele passa — para o computador do escritório em outra cidade, para o servidor que fica sempre ligado, para o desktop de casa. A máquina pega a tarefa, faz, deixa o arquivo onde está e devolve um recibo: onde ele vive, quanto pesa e se confere.

Como ele chega lá não é problema seu. Basta uma pasta que várias máquinas enxerguem: Google Drive, um repositório git privado, Syncthing, um pendrive. Sem servidor, sem banco de dados, sem conta, sem VPN.

## O que você realmente ganha

**1. Leve.**
A caixa de entrada é uma pasta. Sem processo residente, sem banco de dados, nada para vigiar de madrugada. Poucos KB de texto: dá para abrir, ler e levar inteiro.

**2. Sem servidor para implantar.**
Não abre porta, não cria conta, não espera liberação do TI, não precisa de VPN. Se a pasta existe, o sistema está no ar; se não existe, nada quebra.

**3. Vários agentes, uma fila.**
Várias máquinas e IAs diferentes trabalham a mesma fila. Uma tarefa, um responsável: assumir é criar um arquivo que não existe; seis agentes disputam, exatamente um ganha, os outros cinco saem com código 3.

**4. Vários armazenamentos.**
Google Drive, git privado, WebDAV, SSH, S3, pasta local, pendrive: sete backends, os mesmos comandos. Use o que você já tem.

**5. Zero dependências.**
Só a biblioteca padrão do Python, 3.9+. Nada para compilar, sem lockfile, sem cadeia de suprimentos para auditar.

## Instalação

```bash
pip install https://github.com/lx67621956-create/PostBox-M/releases/download/v0.4.0/postbox_m-0.4.0-py3-none-any.whl
```

Do código-fonte: `git clone … && uv tool install .`

## Sessenta segundos

```bash
# máquina A
postbox init --transport local --path "~/Dropbox/caixa-equipe" --agent alice
postbox new --to bob --title "relatorio semanal" --ask "Cinco pontos, só números."

# máquina B
postbox init --transport local --path "~/Dropbox/caixa-equipe" --agent bob
postbox inbox          # 1 tarefa, de alice
postbox ack <id>
postbox result <id> --artifact semanal.md --text "Números da semana 45, fontes no arquivo"
```

Esse é o ciclo inteiro. O resto — `watch`, `lint`, `doctor` — existe para mantê-lo
rodando sem supervisão.

## Escolha um backend

`postbox providers` mostra todas as opções com um comando pronto:

| preset | funciona na China continental | o que é |
|---|---|---|
| `git` | sim | repositório privado no Gitee / GitHub / seu VPS; um commit por escrita |
| `local` | sim | qualquer pasta que sua ferramenta de sincronização já replica |
| `webdav` | sim | Nutstore, Nextcloud, Alist |
| `sftp` | sim | um VPS que você já tem |
| `s3` | depende | MinIO, Cloudflare R2, Aliyun OSS |
| `gdrive` | não | Google Drive |
| `onedrive` / `dropbox` | não | OneDrive, Dropbox |

`local` não precisa de rclone, OAuth, conta nem rede — dois checkouts apontando para a
mesma pasta são uma caixa funcional, que é exatamente como a suíte de testes roda.

## Para os agentes de IA

Uma fila só funciona se todos os agentes seguirem as mesmas regras, então as regras
vêm junto com a ferramenta:

```bash
postbox instructions > AGENTS.md
```

Descreve o ciclo (confirmar antes de trabalhar, manifesto no resultado), as regras
duras (nunca editar o arquivo de outro agente, nunca escrever um segredo) e o
significado dos códigos de saída — qual é "você perdeu a corrida" e qual é "a caixa
não responde". Cole no prompt do sistema, `AGENTS.md`, `CLAUDE.md` ou numa skill do
projeto.

## Letras miúdas

Duas coisas: uma pasta sincronizada só mostra um arquivo depois que o cliente o
entrega, então sonde mais devagar que a latência de sincronização; e quando duas
edições colidem, o cliente de desktop grava `foo (1).md` ao lado de `foo.md` — o
`lint` reporta, e o original fica intacto porque nada aqui é reescrito no lugar.

Mais fundo: [`docs/protocol.md`](docs/protocol.md) (a especificação) e
[`docs/design-notes.md`](docs/design-notes.md) (por que é construído assim).

## Sobre

Feito por **闷闷AI说** — notícias de IA, em chinês, sem hype.

- YouTube: <https://www.youtube.com/@menmenAI>
- Bilibili: <https://space.bilibili.com/34234499>

Licença MIT.
