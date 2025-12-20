/**
 * Alert Service - Error notification via email
 * 
 * Sends email alerts when jobs fail or encounter errors.
 * Integrates with ConfigService for notification settings.
 */

/**
 * Send error alert email
 * @param {string} jobId - Job ID that failed
 * @param {string} errorMessage - Error message
 * @param {Object} context - Additional context (optional)
 */
function sendErrorAlert(jobId, errorMessage, context = {}) {
  const config = new ConfigService().getConfig();
  
  // Check if alerts are enabled
  if (!config.notifications || !config.notifications.enabled) {
    console.log('Alerts disabled, skipping notification');
    return;
  }
  
  const recipient = config.notifications.alert_email;
  if (!recipient) {
    console.warn('Alert email not configured');
    return;
  }
  
  const subject = `[BookSummary] エラー発生: ${jobId}`;
  const timestamp = new Date().toISOString();
  
  const body = `
書籍要約システムのジョブでエラーが発生しました。

========================================
ジョブ情報
========================================
ジョブID: ${jobId}
発生時刻: ${timestamp}
エラー: ${errorMessage}

========================================
コンテキスト
========================================
${JSON.stringify(context, null, 2)}

========================================
調査用リンク
========================================
Cloud Logging (ジョブログ):
https://console.cloud.google.com/logs/query;query=jsonPayload.job_id%3D"${jobId}"

Cloud Storage (ジョブファイル):
https://console.cloud.google.com/storage/browser/[YOUR-BUCKET]/jobs/${jobId}

========================================
このメールは自動送信されています。
  `;
  
  try {
    MailApp.sendEmail(recipient, subject, body);
    console.log(`Alert sent to ${recipient} for job ${jobId}`);
  } catch (e) {
    console.error(`Failed to send alert email: ${e}`);
  }
}

/**
 * Send completion notification (optional)
 * @param {string} jobId - Job ID
 * @param {string} bookTitle - Book title
 * @param {string} gcsUri - GCS URI of generated summary
 */
function sendCompletionNotification(jobId, bookTitle, gcsUri) {
  const config = new ConfigService().getConfig();
  
  // Check if completion alerts are enabled (off by default)
  if (!config.notifications || !config.notifications.alert_on_completion) {
    return;
  }
  
  const recipient = config.notifications.alert_email;
  if (!recipient) return;
  
  const subject = `[BookSummary] 処理完了: ${bookTitle}`;
  const body = `
書籍の要約が完了しました。

タイトル: ${bookTitle}
ジョブID: ${jobId}
出力先: ${gcsUri}

Obsidianで確認できます。
  `;
  
  try {
    MailApp.sendEmail(recipient, subject, body);
    console.log(`Completion notification sent for ${bookTitle}`);
  } catch (e) {
    console.error(`Failed to send completion notification: ${e}`);
  }
}

/**
 * Check for stuck jobs and send alerts
 * This can be set up as a daily trigger to monitor job health
 */
function checkStuckJobs() {
  const config = new ConfigService().getConfig();
  
  // This would require implementing a GCS query for job status
  // For now, this is a placeholder for future implementation
  console.log('Stuck job check not yet implemented');
  
  // Future implementation:
  // 1. Query GCS for jobs/{*}/status.json where status='processing'
  // 2. Check if updated_at is more than 2 hours ago
  // 3. Send alert for stuck jobs
}
