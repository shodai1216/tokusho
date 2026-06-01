# comments-api — CEG コメントAPI

各メンバーページ（`/nene`, `/naran` …）のコメント（ニックネーム＋メッセージ）を保存・取得する小さな FastAPI アプリ。

- 待受: `127.0.0.1:8100`（nginx が `ceg.tokusho.org/api/` からプロキシ）
- DB: SQLite。`COMMENTS_DB` で保存先を指定（本番は `~/data/ceg_comments.db`）
- エンドポイント:
  - `GET  /comments?slug=<slug>` → `{ "comments": [{nickname, message, created_at}, ...] }`（新しい順・最大200件）
  - `POST /comments`（JSON: `{slug, nickname, message, website?}`）→ `{ "ok": true }`
  - `GET  /health`

> nginx は `proxy_pass http://127.0.0.1:8100/;`（末尾スラッシュ）なので、ブラウザの
> `/api/comments` はバックエンドの `/comments` に届く。

## 初回セットアップ（サーバー）

```bash
cd ~/tokusho/comments-api
python3 -m venv venv
venv/bin/pip install -r requirements.txt

mkdir -p ~/data   # SQLite の保存先（git管理外・git pull で消えない）

# systemd 常駐
sudo cp ceg-comments.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ceg-comments
systemctl status ceg-comments --no-pager

# nginx に /api/ プロキシを反映（リポジトリの nginx/ceg.conf を参照）
sudo cp ~/tokusho/nginx/ceg.conf /etc/nginx/sites-available/ceg.conf
sudo nginx -t && sudo systemctl reload nginx
```

## 動作確認

```bash
curl -s 'http://127.0.0.1:8100/health'
curl -s -X POST http://127.0.0.1:8100/comments \
  -H 'Content-Type: application/json' \
  -d '{"slug":"nene","nickname":"test","message":"hello"}'
curl -s 'http://127.0.0.1:8100/comments?slug=nene'
# 外側（nginx経由）
curl -s 'https://ceg.tokusho.org/api/health'
```

## 更新時

```bash
ssh ssh.tokusho.org "cd ~/tokusho && git pull && sudo systemctl restart ceg-comments"
```

> フロント（HTML / comments.js）だけの変更なら `git pull` のみで反映。
> `app.py` を変えたときは `restart ceg-comments` が必要。
