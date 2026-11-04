# PostBox-M

**エージェントが共有できるフォルダ。インフラはそれだけ。**

[English](README.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · 日本語 · [한국어](README.ko.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

互いに到達できないマシン上の複数の AI エージェントが、ひとつの共有キューで作業する。ブローカーも、サーバーも、データベースも、アカウントも、VPN も要らない。エージェントがフォルダを読み書きできるなら——Google Drive、プライベートな git リポジトリ、Syncthing の同期フォルダ、USB メモリ——仕事を回し合える。

## 実際に手に入るもの

**1. 動かし続けるものが無い。**
メールボックスは「フォルダ」そのもの。デーモンを配備する必要も、ポートを開ける必要も、トークンをローテーションする必要も、深夜にブローカーの生死を確認する必要もない。フォルダがあれば、システムは動いている。メッセージバスの運用コストはゼロ。

**2. 1 タスク 1 オーナーを、ファイルシステムが保証する。**
タスクの確保は `create-if-absent`。6 つのエージェントが同じ仕事に殺到しても、成功するのは必ず 1 つ、残り 5 つは終了コード 3 で退く。二重作業が起きないのは、エージェント同士が「合意した」からではなく、片方が**物理的にそのファイルを作れなかった**から。

**3. 何も上書きされない。**
タスクは一度だけ書かれ、二度と編集されない。確認・進捗・納品・ブロック、どの行動も新しいファイルで、名前は一意。だから仕事の履歴は**構造的に**完全になる。git バックエンドなら `git log` が「誰がいつ何を確保したか」を第三者に証明する。

**4. 変化が無ければポーリングは無料。**
`postbox watch` はフォルダに変化が無いあいだ、バイト単位で同一の出力を出して終了コード 0 を返す。cron は出力（あるいは終了コードだけ）を比べて、モデル呼び出しを丸ごと省ける。待機中のエージェントはトークンを消費せず、本当に新しい用事があるときだけ起きる。

**5. 納品物はハッシュ付きのファイルであって、文章ではない。**
`postbox result --artifact report.md` はファイル・フォルダ・サイズ・sha256 を受領書に書き込む。チャットで「完了しました」と言っても納品にはならず、ツールはそれを納品として記録させない。

**6. すでにある場所で動く。**
Gitee のプライベートリポジトリ、Nutstore の WebDAV、自分の VPS への SSH、Google Drive、同じ LAN の 2 台のノート PC。Google アカウントも VPN も inbound ポートも要らない。

**7. 依存ゼロ。**
Python 標準ライブラリのみ、Python 3.9 以上、コマンド 1 つ。ビルド不要、lockfile なし、監査すべきサプライチェーンもなし。

## インストール

```bash
pip install https://github.com/lx67621956-create/PostBox-M/releases/download/v0.4.0/postbox_m-0.4.0-py3-none-any.whl
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
