# PostBox-M

**Donner du travail à un autre ordinateur, même à distance.**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · Français · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

Vous êtes dehors, juste un téléphone. Vous dites à l'assistant du téléphone : passe ça à la machine de la maison. Il le fait — à l'ordinateur du bureau dans une autre ville, au serveur toujours allumé, au poste de la maison. La machine prend la tâche, la fait, garde le fichier chez elle et renvoie un bordereau : où il est, sa taille, et s'il correspond.

Le trajet ne vous regarde pas. Un dossier visible par plusieurs machines suffit : Google Drive, un dépôt git privé, Syncthing, une clé USB. Pas de serveur, pas de base de données, pas de compte, pas de VPN.

## Ce que vous obtenez réellement

**1. Léger.**
La boîte aux lettres, c'est un dossier. Pas de processus résident, pas de base de données, rien à surveiller à 3 h du matin. Quelques Ko de texte : lisible, copiable, transportable tel quel.

**2. Aucun serveur à déployer.**
Pas de port à ouvrir, pas de compte à créer, pas de validation IT, pas de VPN. Si le dossier est là, le système tourne ; s'il n'est pas là, rien ne tombe.

**3. Plusieurs agents, une file.**
Plusieurs machines et plusieurs IA différentes travaillent la même file. Une tâche, un responsable : prendre la tâche, c'est créer un fichier qui n'existe pas ; six agents se précipitent, un seul gagne, les cinq autres sortent avec le code 3.

**4. Plusieurs stockages.**
Google Drive, git privé, WebDAV, SSH, S3, dossier local, clé USB : sept backends, les mêmes commandes. Prenez celui que vous avez déjà.

**5. Zéro dépendance.**
Bibliothèque standard Python uniquement, 3.9+. Rien à compiler, pas de lockfile, pas de chaîne d'approvisionnement à auditer.

## Installation

```bash
pip install https://github.com/lx67621956-create/PostBox-M/releases/download/v0.4.0/postbox_m-0.4.0-py3-none-any.whl
```

Depuis les sources : `git clone … && uv tool install .`

## Soixante secondes

```bash
# machine A
postbox init --transport local --path "~/Dropbox/boite-equipe" --agent alice
postbox new --to bob --title "rapport hebdo" --ask "Cinq points, des chiffres uniquement."

# machine B
postbox init --transport local --path "~/Dropbox/boite-equipe" --agent bob
postbox inbox          # 1 tâche, d'alice
postbox ack <id>
postbox result <id> --artifact hebdo.md --text "Chiffres de la semaine 45, sources dans le fichier"
```

C'est toute la boucle. Le reste — `watch`, `lint`, `doctor` — sert à la faire tourner sans surveillance.

## Choisir un backend

`postbox providers` affiche toutes les options avec une commande prête à l'emploi :

| préréglage | fonctionne en Chine continentale | ce que c'est |
|---|---|---|
| `git` | oui | un dépôt privé sur Gitee / GitHub / votre VPS ; un commit par écriture |
| `local` | oui | n'importe quel dossier que votre outil de synchronisation réplique déjà |
| `webdav` | oui | Nutstore, Nextcloud, Alist |
| `sftp` | oui | un VPS que vous possédez déjà |
| `s3` | selon | MinIO, Cloudflare R2, Aliyun OSS |
| `gdrive` | non | Google Drive |
| `onedrive` / `dropbox` | non | OneDrive, Dropbox |

`local` n'exige ni rclone, ni OAuth, ni compte, ni réseau : deux checkouts pointés sur le même dossier forment une boîte aux lettres fonctionnelle — exactement la configuration de la suite de tests.

## Pour les agents d'IA

Une file ne fonctionne que si tous les agents respectent les mêmes règles, alors les règles sont livrées avec l'outil :

```bash
postbox instructions > AGENTS.md
```

Il décrit la boucle (accuser réception avant de travailler, manifeste dans le résultat), les règles dures (ne jamais éditer le fichier d'un autre agent, ne jamais écrire un secret) et la signification des codes de sortie — lequel veut dire « vous avez perdu la course », lequel veut dire « la boîte est injoignable ». Collez-le dans le prompt système, `AGENTS.md`, `CLAUDE.md` ou une skill du projet.

## Petites lignes

Deux choses à savoir : un dossier synchronisé n'affiche un fichier qu'une fois livré par le client, donc sondez plus lentement que votre latence de synchronisation ; et quand deux éditions se heurtent, le client de bureau écrit `foo (1).md` à côté de `foo.md` — `lint` le signale, et l'original reste intact, car rien ici n'est jamais réécrit sur place.

Pour aller plus loin : [`docs/protocol.md`](docs/protocol.md) (la spécification) et [`docs/design-notes.md`](docs/design-notes.md) (pourquoi c'est construit ainsi).

## À propos

Réalisé par **闷闷AI说** — l'actualité de l'IA, en chinois, sans hype.

- YouTube : <https://www.youtube.com/@menmenAI>
- Bilibili : <https://space.bilibili.com/34234499>

Licence MIT.
