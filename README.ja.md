# PostBox-M

**外出先からでも、別のパソコンに仕事を頼める。**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · 日本語 · [한국어](README.ko.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

外にいて、手元にはスマホだけ。スマホのアシスタントに言う：これは家のパソコンに渡して。それだけで、別の街の会社のパソコンへ、電源を切らないサーバーへ、家のデスクトップへ渡してくれる。受け取ったマシンが自分でやり、ファイルはその場に置いたまま、どこに・どれくらいの大きさで・一致するかを書いた伝票を返してくる。

途中の経路は知らなくていい。複数のマシンが見られるフォルダがひとつあれば足りる。Google Drive、プライベートな git、Syncthing、USB メモリ。サーバーも、データベースも、アカウントも、VPN も要らない。

## 実際に手に入るもの

**1. 軽い。**
メールボックスはフォルダそのもの。常駐プロセスも、データベースも、夜中に見張るものもない。中身は数 KB のテキストで、開いて読めて、丸ごと持ち運べる。

**2. サーバーの設置が不要。**
ポートを開けず、アカウントも作らず、IT の許可も VPN も要らない。フォルダがあれば動き、なくても壊れるものがない。

**3. 複数エージェントで 1 本のキュー。**
何台ものマシンと、違う種類の AI が同じキューで働く。仕事の担当は 1 人だけ：受け取りは「存在しないファイルを作る」ことで、6 体が同時に奪い合っても成功するのは 1 体、残りはコード 3 で降りる。

**4. 保存先は選べる。**
Google Drive、プライベート git、WebDAV、SSH、S3、ローカル、USB メモリの 7 種類。コマンドは同じです。手元にあるものを使えばいい。

**5. 依存ゼロ。**
Python 標準ライブラリのみ、3.9 以上、コマンド 1 つ。ビルドも lockfile も、監査すべき依存もない。

## インストール

```bash
pip install "git+https://github.com/lx67621956-create/PostBox-M.git"
```

ソースからなら `git clone … && uv tool install .`

## 60 秒で動かす

```bash
# マシン A
postbox init --transport local --path "~/Dropbox/team-inbox" --agent alice
postbox new --to bob --title "週次レポート" --ask "要点は 5 つ、数字だけで。"

# マシン B
postbox init --transport local --path "~/Dropbox/team-inbox" --agent bob
postbox inbox          # 1 件、alice から
postbox ack <id>
postbox result <id> --artifact weekly.md --text "第 45 週の数字、出典はファイル内"
```

ループはこれだけ。残りの `watch`・`lint`・`doctor` は、無人で回し続けるためのもの。

## バックエンドを選ぶ

`postbox providers` が全候補と実行できるコマンドを表示する:

| プリセット | 中国本土で使えるか | 内容 |
|---|---|---|
| `git` | はい | Gitee / GitHub / 自前 VPS のプライベートリポジトリ。書き込み 1 回につき 1 コミット |
| `local` | はい | 既存の同期ツールが複製している任意のフォルダ |
| `webdav` | はい | Nutstore、Nextcloud、Alist |
| `sftp` | はい | すでに持っている VPS |
| `s3` | 条件次第 | MinIO、Cloudflare R2、Aliyun OSS |
| `gdrive` | いいえ | Google Drive |
| `onedrive` / `dropbox` | いいえ | OneDrive、Dropbox |

`local` は rclone も OAuth もアカウントもネットワークも不要。同じフォルダを指す 2 つのチェックアウトが、そのまま動くメールボックスになる。テストスイートもその構成で走っている。

## AI エージェントのために

キューが機能するかどうかは、全エージェントが同じルールを守るかにかかっている。だからルールもツールに同梱している:

```bash
postbox instructions > AGENTS.md
```

ループ（作業前に確保する、結果にはマニフェストを付ける）、固い決まり（他人のファイルを編集しない、秘密情報を書かない）、そして終了コードの意味——どれが「競争に負けた」で、どれが「メールボックスに届かない」か——が書いてある。システムプロンプト、`AGENTS.md`、`CLAUDE.md`、プロジェクトの skill に貼ればよい。

## 細かい但し書き

2 点だけ: 同期フォルダはクライアントが届けて初めてファイルが見えるので、ポーリング間隔は同期の遅延より長くすること。もう 1 つ、2 つの編集が衝突するとデスクトップクライアントは `foo.md` の隣に `foo (1).md` を作る。`lint` が報告し、元のファイルは無傷のまま——このシステムは何もその場で書き換えないから。

詳しくは [`docs/protocol.md`](docs/protocol.md)（仕様）と [`docs/design-notes.md`](docs/design-notes.md)（設計理由）。

## について

**闷闷AI说** による作品。中国語で AI ニュースを、誇張なしで。

- YouTube: <https://www.youtube.com/@menmenAI>
- Bilibili: <https://space.bilibili.com/34234499>

MIT ライセンス。
