/**
 * RefactorJob.gs
 * Weekly automated Concepts Index review trigger with email notification.
 */

const ANALYZE_URL = PropertiesService.getScriptProperties().getProperty('ANALYZE_URL') || '';

/**
 * Main function to be called by time-driven trigger.
 * Calls Cloud Function to analyze Concepts Index and sends email report.
 */
function runWeeklyReview() {
  try {
    const response = UrlFetchApp.fetch(ANALYZE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      muteHttpExceptions: true
    });
    
    const statusCode = response.getResponseCode();
    // Explicitly specify charset just in case, though usually automatic
    const resultText = response.getContentText("UTF-8");
    
    if (statusCode !== 200) {
      sendErrorEmail("Concepts Index Analysis Failed", `Status: ${statusCode}\n${resultText}`);
      return;
    }
    
    const result = JSON.parse(resultText);
    
    if (result.status !== "success") {
      sendErrorEmail("Concepts Index Analysis Error", result.message || "Unknown error");
      return;
    }
    
    sendReportEmail(result.report);
    
  } catch (e) {
    sendErrorEmail("Concepts Index Analysis Exception", e.toString());
  }
}

/**
 * Formats and sends the weekly report email.
 */
function sendReportEmail(report) {
  const recipient = Session.getActiveUser().getEmail();
  const subject = "[Weekly] Concepts Index Review Report";
  
  let html = `
    <h2>Concepts Index Weekly Review</h2>
    <p><strong>Last Updated:</strong> ${report.last_updated}</p>
    <p><strong>Total Concepts:</strong> ${report.total_concepts}</p>
    
    <h3>Hub Concepts (3+ sources)</h3>
  `;
  
  if (report.hub_concepts && report.hub_concepts.length > 0) {
    html += "<ul>";
    for (const hub of report.hub_concepts) {
      html += `<li><strong>${hub.name}</strong> (${hub.count} sources)</li>`;
    }
    html += "</ul>";
  } else {
    html += "<p>None</p>";
  }
  
  html += "<h3>Potential Duplicates (Top 20)</h3>";
  
  if (report.potential_duplicates && report.potential_duplicates.length > 0) {
    html += "<ul>";
    for (const dup of report.potential_duplicates) {
      html += `<li>[${Math.round(dup.similarity * 100)}%] "${dup.pair[0]}" vs "${dup.pair[1]}"</li>`;
    }
    html += "</ul>";
  } else {
    html += "<p>None</p>";
  }
  
  html += "<h3>JP/EN Notation Pairs (Top 10)</h3>";
  
  if (report.jp_en_pairs && report.jp_en_pairs.length > 0) {
    html += "<ul>";
    for (const pair of report.jp_en_pairs) {
      html += `<li>"${pair.with_notation}" ↔ "${pair.without_notation}"</li>`;
    }
    html += "</ul>";
  } else {
    html += "<p>None</p>";
  }
  
  html += `
    <hr>
    <p style="color: #666; font-size: 12px;">
      This email is automatically generated.<br>
      To merge duplicates or fix links, please run <code>refactor_concepts.py</code>.
    </p>
  `;
  
  GmailApp.sendEmail(recipient, subject, "", { htmlBody: html });
  console.log(`Weekly review email sent to: ${recipient}`);
}

/**
 * Sends error notification email.
 */
function sendErrorEmail(title, message) {
  const recipient = Session.getActiveUser().getEmail();
  GmailApp.sendEmail(recipient, `【エラー】${title}`, message);
  console.error(`Error email sent: ${title}`);
}

/**
 * Manual test function - run from GAS editor to verify setup.
 */
function testWeeklyReview() {
  runWeeklyReview();
}
