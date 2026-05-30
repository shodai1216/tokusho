# tokusho — サーバー管理リポジトリ

Tokura Shodai の自宅サーバー上で動作するサービス一式。

## フォルダ構成

```
tokusho/
├── smartlock/       # SmartLock API（FastAPI）
│   ├── app/         # サーバーサイドコード
│   └── static/      # Web UI（index.html）
├── portfolio/       # ポートフォリオサイト（tokusho.dev）
├── nginx/           # Nginx 設定ファイル
│   ├── portfolio.conf
│   └── smartlock.conf
└── docker/
    └── cloudflare-tunnel.yml  # Cloudflare Tunnel 設定
```

## 関連リポジトリ

| リポジトリ | 場所 | 用途 |
|---|---|---|
| `tokusho`（このリポジトリ） | `C:\Users\shoda\code\tokusho\` | サーバー・ウェブサービス全般 |
| `smartlock-ino` | `C:\Users\shoda\code\IOT\smartlock\` | Arduino / ESP32 コード・手順書 |

## サブドメイン

| URL | サービス |
|---|---|
| `tokusho.dev` | ポートフォリオ |
| `home.tokusho.dev` | SmartLock ダッシュボード |
| `files.tokusho.dev` | Nextcloud（ファイルサーバー） |
| `dev.tokusho.dev` | 開発・テスト用 |

## サーバーへのデプロイ

```bash
# smartlock API を更新
ssh shodai@192.168.1.10 "cd ~/tokusho && git pull && sudo systemctl restart smartlock"

# ポートフォリオを更新（git pull だけで即反映）
ssh shodai@192.168.1.10 "cd ~/tokusho && git pull"
```

## Ubuntu サーバー上の構成

```
~/tokusho/           ← git clone したこのリポジトリ
~/www/
└── portfolio/       ← ~/tokusho/portfolio へのシンボリックリンク
```
