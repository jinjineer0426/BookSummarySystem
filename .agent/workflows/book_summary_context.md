---
description: Book Summary System Architecture and Context
---

# Book Summary System Context

このドキュメントは、Book Summary System のアーキテクチャとコンテキストを共有するためのものです。

## システム概要

PDF書籍からサマリーを生成し、Obsidian Vault (GCS) に同期するシステム。

Flow:

1. **Google Drive**: PDFアップロード (ユーザー)
2. **GAS (Trigger.gs)**: 5分ごとに検知 → Cloud Run (process_book) 呼び出し
3. **Cloud Run (Orchestrator)**:
   - Job ID生成
   - Cloud Tasks (prepare_book) にキューイング
   - GASに即時レスポンス (200 OK)
4. **Cloud Run (Worker - Prepare)**:
   - PDFダウンロード & テキスト抽出
   - TOC抽出 (Vision AI -> Regex Fallback -> Full Text)
   - 章ごとに分割し、各章を Cloud Tasks (process_chapter) にキューイング
5. **Cloud Run (Worker - Chapter)**:
   - 各章を Gemini 2.5 Flash で要約
   - 結果を GCS (jobs/{job_id}/chapters/) に保存
6. **Cloud Run (Worker - Finalizer)**:
   - 全章の完了を検知 -> 書籍全体のまとめ作成
   - Metadata生成 (Concept Normalization)
   - **GCS (obsidian_vault)** にMarkdown書き込み
7. **GAS**: 処理結果をスプレッドシートにログ出力
8. **Obsidian**: Remotely Save プラグインで GCS から同期

## GCSディレクトリ構成 (Obsidian Vault)

- `00_Inbox/`: クリップ記事（未処理の入り口）
- `01_Reading/`: 書籍サマリー
- `02_Knowledge/`: 概念インデックス
- `03_Projects/`: プロジェクト関連
- `99_Archive/`: アーカイブ
- `config/`: システム設定ファイル

## 重要ファイル

- **Cloud Function**: `/Users/takagishota/Documents/KnowledgeBase/BookSummarySystem/cloud_function/main.py`
  - GCSバケット: `obsidian_vault_sync_my_knowledge`
  - 処理ロジック: `process_book` (Entry), `prepare_book`, `process_chapter`, `finalize_book`
- **GAS**: `/Users/takagishota/Documents/KnowledgeBase/BookSummarySystem/gas/Trigger.gs`
  - トリガー管理、ログ記録
- **Deployment Guide**: `/Users/takagishota/Documents/KnowledgeBase/BookSummarySystem/DEPLOY.md`
- **Obsidian Setup**: `/Users/takagishota/Documents/KnowledgeBase/ObsidianSync/SETUP_GUIDE.md`

## デプロイコマンド

```bash
# Cloud Function
cd ~/Documents/KnowledgeBase/BookSummarySystem/cloud_function
gcloud run deploy process-book \
  --source . \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --update-env-vars "OBSIDIAN_BUCKET_NAME=obsidian_vault_sync_my_knowledge,CLOUD_TASKS_QUEUE=book-summary-queue,FUNCTION_URL=[YOUR_CLOUD_RUN_URL]"
```

## 現在のステータス (2025-12-31)

- Architecture: Cloud Run + Cloud Tasks による完全非同期並列処理
- AI Model: Gemini 2.5 Flash (Text & Vision)
- TOC Extraction:
  - Primary: Vision AI (Gemini 2.5 Flash) による目次画像解析
  - Fallback: Regex による章タイトル検出 (Runaway detection limit: 100)
- Logging: 構造化ログ (JobLogger) と JobTracker による詳細なステータス管理
- Others: GitHub CI/CD連携済み (clasp)
