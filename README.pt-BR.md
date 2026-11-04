# PostBox-M

**Uma pasta que seus agentes podem compartilhar. Essa é toda a infraestrutura.**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · Português

Dois ou mais agentes de IA, em máquinas que não conseguem se comunicar, trabalhando
uma fila compartilhada. Sem broker, sem servidor, sem banco de dados, sem conta, sem
VPN. Se seus agentes sabem ler e escrever uma pasta — Google Drive, um repositório
git privado, um par Syncthing, um pendrive —, eles conseguem passar trabalho entre si.

## O que você realmente ganha

**1. Nada para manter no ar.**
A caixa de entrada *é* uma pasta. Nenhum daemon para implantar, nenhuma porta para
abrir, nenhum token para rotacionar, nenhum broker para manter vivo às 3 da manhã.
Se a pasta existe, o sistema está funcionando. A conta de infraestrutura do barramento
de mensagens é zero.

**2. Um dono por tarefa, garantido pelo sistema de arquivos.**
Assumir um trabalho é `create-if-absent`. Seis agentes disputando a mesma tarefa:
exatamente um consegue, os outros cinco saem com código 3 e recuam. O trabalho
duplicado deixa de acontecer porque dois agentes "combinaram" — deixa porque um deles
**fisicamente não conseguiu criar o arquivo**.

**3. Nada é sobrescrito.**
Uma tarefa é escrita uma vez e nunca editada. Cada ação — confirmação, nota, entrega,
bloqueio — é um arquivo novo com nome único. O histórico de um trabalho fica completo
por construção, não por disciplina; e no backend git, `git log` prova a um terceiro
quem assumiu o quê e quando.

**4. Sondar não custa nada quando nada aconteceu.**
`postbox watch` imprime saída idêntica byte a byte enquanto a pasta não muda e sai
com 0. Um cron compara a saída — ou só o código de saída — e pula totalmente a chamada
ao modelo. Um agente ocioso custa zero token e só acorda quando há algo novo de verdade.

**5. Uma entrega é um arquivo com hash, não uma frase.**
`postbox result --artifact relatorio.md` grava arquivo, pasta, tamanho e sha256 no
recibo. "Feito" dito no chat não é entrega, e a ferramenta não deixa um agente
registrar isso como tal.

**6. Roda onde você já está.**
Um repositório privado no Gitee, uma pasta WebDAV do Nutstore, um VPS por SSH, Google
Drive, dois notebooks na mesma LAN. Ninguém precisa de conta Google, de VPN nem de
abrir porta de entrada.

**7. Zero dependências.**
Só a biblioteca padrão do Python, Python 3.9+, um comando. Nada para compilar, sem
lockfile, sem cadeia de suprimentos para auditar.

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
