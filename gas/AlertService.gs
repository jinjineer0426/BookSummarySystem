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


