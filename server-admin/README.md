# server-admin — Tokusho サーバー管理API

apex（tokusho.org）の管理ポータル用バックエンド。稼働状況の確認・許可サービスの
再起動・ログ閲覧だけを行う小さな FastAPI アプリ。

- 待受: `127.0.0.1:8200`（nginx が `tokusho.org/admin/api/` からプロキシ）
- **apex 全体が nginx の Basic認証で保護**されているので、このAPIも認証の内側でしか叩けない
- 操作対象は `app.py` の `ALLOWED` 許可リストのみ
- エンドポイント:
  - `GET  /status` … サービス稼働状況＋システム情報（uptime/load/disk/mem）
  - `POST /restart` … `{ "service": "<id>" }` 許可サービスを再起動
  - `GET  /logs?service=<id>&lines=100` … journalctl ログ
  - `GET  /health`

## 初回セットアップ（サーバー）

```bash
cd ~/tokusho/server-admin
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 1) 特権コマンドの許可（restart / journalctl のみ・NOPASSWD）
#    ※ systemctl / journalctl の絶対パスを command -v で確認して必要なら sudoers を修正
sudo cp sudoers.tokusho-admin /etc/sudoers.d/tokusho-admin
sudo chmod 0440 /etc/sudoers.d/tokusho-admin
sudo visudo -cf /etc/sudoers.d/tokusho-admin     # parsed OK が出ればOK

# 2) 常駐
sudo cp tokusho-admin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tokusho-admin
systemctl status tokusho-admin --no-pager

# 3) Basic認証ファイルを作成（apex を本人専用にする）
sudo apt-get install -y apache2-utils   # htpasswd が無ければ
sudo htpasswd -c /etc/nginx/.htpasswd_tokusho shodai   # パスワード入力

# 4) nginx に Basic認証＋/admin/api/ プロキシを反映（nginx/home.conf を参照）
#    ※ apex の実体ファイル名は環境依存（ceg は拡張子なし "ceg" だった）。
#    まず実体を確認:  ls -l /etc/nginx/sites-enabled/ | grep -E 'tokusho|home|default'
#    その実体に home.conf の内容を反映してから:
sudo nginx -t && sudo systemctl reload nginx
```

## 動作確認

```bash
curl -s http://127.0.0.1:8200/health                 # {"ok":true}
curl -s http://127.0.0.1:8200/status | head          # ローカル直叩き
curl -s -u shodai 'https://tokusho.org/admin/api/health'   # nginx経由（Basic認証）
sudo -n systemctl restart nginx                      # sudoers が効いているか（パスワードを聞かれなければOK）
```

## サービスを増やすとき

1. `app.py` の `ALLOWED` にユニット名を追加
2. `sudoers.tokusho-admin` の restart 行と journalctl 行を追加し、`/etc/sudoers.d/` に再反映
3. `git pull && sudo systemctl restart tokusho-admin`

## 更新時

```bash
ssh ssh.tokusho.org "cd ~/tokusho && git pull && sudo systemctl restart tokusho-admin"
```
