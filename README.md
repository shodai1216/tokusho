# tokusho — ウェブサイト リポジトリ

Tokura Shodai の自宅サーバー上で配信するウェブサイト群。  
（SmartLock の IoT・API は別リポジトリ `smartlock` に分離）

## フォルダ構成

**ルール：トップレベルの各フォルダ = 1サイト = 1サブドメイン**

```
tokusho/
├── home/         # tokusho.org（apex・トップページ "Shodai'home"）
├── portfolio/    # portfolio.tokusho.org
├── ceg/          # ceg.tokusho.org（CEG飲み部メンバー紹介）
│   ├── index.html      # メンバー一覧
│   ├── naran/          # /naran
│   └── nene/           # /nene
├── nginx/        # Nginx 設定の参考コピー（実体は /etc/nginx/sites-available/）
│   ├── home.conf
│   ├── portfolio.conf
│   └── ceg.conf
├── docker/
│   └── cloudflare-tunnel.yml  # Tunnel設定の参考（実体は /etc/cloudflared/config.yml）
├── docs/
│   └── ceg_member_template.md # CEGメンバー追加用テンプレ
├── comments-api/ # CEGコメントAPI（FastAPI+SQLite, systemd常駐）
├── server-admin/ # apex管理ポータルのAPI（FastAPI, systemd常駐, Basic認証の内側）
└── photo/        # 元画像素材（配信しない）
```

> 内部リンク・アセットは**ルート相対**（`/`, `/naran`, `/naran/naran.jpg`）で書く。  
> 配信構造に依存した絶対パス（`/static/...`）は使わない。

## サブドメイン

| URL | サイト | docroot |
|---|---|---|
| `tokusho.org` / `www` | トップpage | `home/` |
| `portfolio.tokusho.org` | ポートフォリオ | `portfolio/` |
| `ceg.tokusho.org` | CEG メンバー紹介 | `ceg/` |
| `home.tokusho.org` | SmartLock ダッシュボード（別repo） | — |
| `ssh.tokusho.org` | URL経由SSH | — |

> ⚠️ `home/` フォルダ（apex）と `home.tokusho.org`（SmartLock）は別物。名前が紛らわしいので注意。

## 関連リポジトリ

| リポジトリ | Windows | サーバー | 用途 |
|---|---|---|---|
| `tokusho`（本repo） | `code\tokusho` | `~/tokusho` | ウェブサイト全般 |
| `smartlock` | `code\IOT\smartlock` | `~/smartlock-api` | ESP32コード・SmartLock API |

## サーバーへのデプロイ

```bash
# サイト更新（git pull だけで即反映。Nginxが ~/www/<name> を配信）
ssh ssh.tokusho.org "cd ~/tokusho && git pull"
```

> CEGのコメント機能（`comments-api/`）の `app.py` を変更したときは、API再起動も必要：
> `ssh ssh.tokusho.org "cd ~/tokusho && git pull && sudo systemctl restart ceg-comments"`
> 初回セットアップ手順は `comments-api/README.md` を参照。

> apex（tokusho.org）は管理ポータル。Basic認証で保護し、`server-admin/`（FastAPI）が
> サービスの稼働確認・再起動・ログ閲覧を担う。初回セットアップ（venv / sudoers / systemd /
> htpasswd / nginx）は `server-admin/README.md` を参照。`app.py` 変更時は
> `... && sudo systemctl restart tokusho-admin`。

## サーバー上の構成

```
~/tokusho/                     ← git clone したこのリポジトリ
~/www/
├── home      -> ~/tokusho/home
├── portfolio -> ~/tokusho/portfolio
└── ceg       -> ~/tokusho/ceg
```

新サイト追加・Nginx/Tunnel設定の手順は `smartlock` リポジトリの `SERVER_TIPS.md` を参照。
