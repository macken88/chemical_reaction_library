# Chemical Reaction Library

化学反応の構造表現、反応物・生成物・試薬・条件、検証結果を SQLite に保存して検索する、ローカル利用向けの反応ライブラリです。機械的な構造・元素・電荷・原子価・atom mapping の検証を行います。

> **注意:** この検証は入力表現の機械的な整合性を確認するものです。反応が実験・現実に成立すること、収率や安全性を保証するものではありません。結果は必ず専門家の判断と一次情報で確認してください。

## 前提

- Windows / PowerShell
- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)（Python 環境・依存管理）
- Node.js / npm（フロントエンド開発サーバー）

## 初回セットアップ

```powershell
uv sync
Push-Location frontend
npm install
Pop-Location
```

Ketcher は npm 依存としてフロントエンドにローカル埋め込みされるため、外部 URL や追加の環境設定は必要ありません。

## 開発起動

リポジトリのルートで次を実行します。必要な依存が未作成の場合だけインストールし、FastAPI と Vite の準備が整うまで待機します。

```powershell
.\scripts\run-dev.ps1
```

FastAPI は `http://127.0.0.1:8000`、Vite は `http://127.0.0.1:5173` で待ち受けます。ブラウザを開かない場合は `-NoBrowser`、依存インストールを省略する場合は `-SkipInstall`、起動確認だけ行って終了する場合は `-SmokeTest` を付けます。終了時は Ctrl+C（子プロセスも停止）です。

## データとバックアップ

既定のデータベースは `data/reaction_library.sqlite3` です。環境変数 `REACTION_LIBRARY_DATABASE_URL` で SQLite の保存先を変更できます。バックアップは `data/backups/`（または指定したデータベースと同じディレクトリの `backups/`）に作成されます。

バックアップは別の安全な場所にもコピーしてください。リストアは現在のデータベースを置き換える操作なので、実行前に新しいバックアップを取得し、対象ファイルとスキーマバージョンを確認してください。アプリは無効な SQLite や異なるスキーマのバックアップを拒否します。

## 画面と基本ワークフロー

主な画面は次の4つです。

1. **Editor（反応入力）** — 構造エディタ、成分・試薬・条件・タグの入力
2. **Import（外部表現の取り込み）** — Reaction SMILES / RXN を Draft に変換
3. **Validation（検証）** — 構造、元素・電荷収支、atom mapping などの結果と警告の確認
4. **Library（ライブラリ）** — 保存済み反応の一覧・検索・再検証・削除。バックアップ取得とリストアもこの画面から行います

「Import」または「Editor」で Draft を準備 → 「Validation」で結果と警告を確認 → 必要なら Editor に戻って修正・再検証 → 保存 → Library で検索・バックアップ、の順で利用します。検証に通っても現実の反応成立を意味しない点に注意してください。

## テスト

```powershell
uv run pytest -q
Push-Location frontend
npm test -- --run
npm run typecheck
Pop-Location
```

`git diff --check` で空白エラーも確認できます。
