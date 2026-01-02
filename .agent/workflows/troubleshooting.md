---
description: システムエラーやバグのトラブルシューティング手順
---

# トラブルシューティングワークフロー

問題発生時に体系的にデバッグを進めるための標準手順。

---

## 1. エラーメッセージの確認

- [ ] エラーログを取得（Cloud Logging、GCS、ローカルログなど）
- [ ] エラーメッセージの全文を記録
- [ ] 発生日時、影響を受けたジョブID/ファイルIDを特定
- [ ] 既知のエラーパターンとの照合

**使用ツール例:**

```bash
# Cloud Loggingからログ取得
gcloud logging read "resource.type=cloud_run_revision AND severity>=ERROR" --limit 50

# GCSからステータス確認
gsutil cat gs://BUCKET/jobs/JOB_ID/status.json
gsutil cat gs://BUCKET/jobs/JOB_ID/errors.json
```

---

## 2. 原因の推測

- [ ] エラーメッセージから直接的な原因を推測
- [ ] 関連するコードを特定（grep_search、view_file）
- [ ] 最近の変更履歴を確認（git log、git diff）
- [ ] 仮説を複数立てる（優先度順にリスト化）

**チェックポイント:**

- 設定値の問題か？（環境変数、GCS config）
- コードロジックの問題か？
- 外部サービス（API、認証）の問題か？
- データ固有の問題か？（特定のファイルでのみ発生）

---

## 3. 再現テスト

- [ ] 問題を再現するテストスクリプトを作成
- [ ] ローカル環境で再現を試みる
- [ ] 再現できた場合：原因特定に進む
- [ ] 再現できない場合：環境差異を調査

**テストスクリプトの要件:**

```python
#!/usr/bin/env python3
"""
Reproduction test for [問題の概要]
"""
# 1. 環境変数の読み込み（.env）
from dotenv import load_dotenv
load_dotenv()

# 2. 必要なサービスの初期化
# 3. 問題を再現する最小限のコード
# 4. 期待値との比較
# 5. 結果をJSONで保存
```

---

## 4. 適切な対策の絞り込み

- [ ] 複数の解決策を列挙
- [ ] 各解決策のメリット・デメリットを評価
- [ ] 実装コスト、リスク、効果を考慮して選択

**評価基準:**

| 観点 | 質問 |
|:---|:---|
| 効果 | 問題を根本的に解決するか？ |
| リスク | 副作用や新たなバグを生む可能性は？ |
| コスト | 実装にどれくらいの時間がかかるか？ |
| 保守性 | 将来的なメンテナンスは容易か？ |

---

## 5. 実行計画の策定

- [ ] `implementation_plan.md` を作成
- [ ] 変更対象ファイルと具体的な修正内容を記載
- [ ] 検証手順（テストコマンド、確認項目）を明記
- [ ] ユーザーにレビューを依頼

**計画テンプレート:**

```markdown
# [問題タイトル]

## 問題の背景
[何が起きているか、影響範囲]

## Proposed Changes
### [Component Name]
#### [MODIFY/NEW/DELETE] [filename]
- 変更内容1
- 変更内容2

## Verification Plan
1. ローカルテスト: `python3 scripts/test_xxx.py`
2. デプロイ後確認: [確認手順]
```

---

## 6. 実行

- [ ] コード修正を実施
- [ ] ローカルテストで修正を検証
- [ ] 本番環境にデプロイ
- [ ] 本番環境で動作確認
- [ ] ドキュメントを更新
- [ ] 変更をGitにコミット・プッシュ

**デプロイコマンド例:**

```bash
# Cloud Run デプロイ
gcloud run deploy SERVICE_NAME --source . --project PROJECT_ID --region REGION

# 動作確認
curl -X POST https://SERVICE_URL -H "Content-Type: application/json" -d '{"file_id": "xxx"}'
```

---

## 完了チェックリスト

- [ ] 問題が解決したことを確認
- [ ] 同様の問題が再発しないよう予防策を実装
- [ ] ドキュメント（ARCHITECTURE.md, TOC_EXTRACTION.md等）を更新
- [ ] GitHubに変更をプッシュ
- [ ] 必要に応じてユーザーに完了報告
