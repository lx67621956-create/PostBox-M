# PostBox-M

**Un dossier que vos agents peuvent partager. C'est toute l'infrastructure.**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · Français · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

Deux agents d'IA ou plus, sur des machines qui ne peuvent pas communiquer entre elles, travaillant une file d'attente commune. Pas de broker, pas de serveur, pas de base de données, pas de compte, pas de VPN. Si vos agents savent lire et écrire un dossier — Google Drive, un dépôt git privé, une paire Syncthing, une clé USB —, ils peuvent se passer du travail.

## Ce que vous obtenez réellement

**1. Rien à faire tourner.**
La boîte aux lettres *est* un dossier. Aucun démon à déployer, aucun port à ouvrir, aucun jeton à faire tourner, aucun broker à surveiller à 3 h du matin. Si le dossier existe, le système est en marche. Le coût d'infrastructure du bus de messages est nul.

**2. Un seul propriétaire par tâche, garanti par le système de fichiers.**
Prendre une tâche, c'est `create-if-absent`. Six agents sur la même tâche : exactement un réussit, les cinq autres sortent avec le code 3 et se retirent. Le double travail disparaît non pas parce que deux agents « se sont mis d'accord », mais parce que l'un d'eux **n'a physiquement pas pu créer le fichier**.

**3. Rien n'est jamais écrasé.**
Une tâche est écrite une fois et jamais éditée. Chaque action — accusé, note, livraison, blocage — est un fichier nouveau au nom unique. L'historique d'un travail est donc complet par construction, pas par discipline ; et avec le backend git, `git log` prouve à un tiers qui a pris quoi et quand.

**4. Sonder ne coûte rien quand il ne s'est rien passé.**
`postbox watch` imprime une sortie identique octet pour octet tant que le dossier ne change pas et sort avec 0. Un cron compare la sortie — ou juste le code de sortie — et saute entièrement l'appel au modèle. Un agent au repos coûte zéro jeton et ne se réveille que s'il y a vraiment du nouveau.

**5. Une livraison est un fichier avec un hash, pas une phrase.**
`postbox result --artifact report.md` inscrit fichier, dossier, taille et sha256 dans le reçu. « C'est fait » dit dans un chat n'est pas une livraison, et l'outil ne laisse pas un agent l'enregistrer comme telle.

**6. Tourne là où vous êtes déjà.**
Un dépôt privé sur Gitee, un dossier WebDAV Nutstore, un VPS en SSH, Google Drive, deux portables sur le même LAN. Personne n'a besoin d'un compte Google, d'un VPN, ni d'ouvrir un port entrant.

**7. Zéro dépendance.**
Bibliothèque standard Python uniquement, Python 3.9+, une commande. Rien à compiler, pas de lockfile, pas de chaîne d'approvisionnement à auditer.

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
