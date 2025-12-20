/**
 * GcsStorage.gs - GCS Access for Job Status Sync
 * Reads completed job metadata from GCS and updates spreadsheet.
 * 
 * NOTE: This file uses CONFIG from Trigger.gs (same GAS project)
 */

// === Configuration (Unified via ConfigService) ===
function getGcsConfig_() {
  const config = new ConfigService().getConfig();
  const props = PropertiesService.getScriptProperties();
  
  return {
    GCS_BUCKET: props.getProperty('GCS_BUCKET') || 
                config.gcs?.bucket_name || 
                'my-book-summary-config',
    JOBS_PREFIX: 'jobs/'
  };
}

/**
 * Syncs completed jobs from GCS to the spreadsheet.
 * Optimized to only check recently updated files to stay within GAS limits.
 */
function syncCompletedJobs() {
  const sheet = getLogSheet();
  const fileIdMap = getFileIdMap(sheet);
  
  // Get metadata files updated in the last 72 hours (3 days)
  // This provides a safe buffer for a daily trigger.
  const recentMetadataObjects = listRecentMetadataObjects(72);
  console.log(`Found ${recentMetadataObjects.length} recently updated metadata files in GCS`);
  
  let syncedCount = 0;
  
  for (const obj of recentMetadataObjects) {
    // Extract jobId from path: "jobs/{jobId}/metadata.json"
    const pathParts = obj.name.split('/');
    if (pathParts.length < 2) continue;
    const jobId = pathParts[1];
    
    // Read the actual content of the metadata.json
    const metadata = readJobMetadata(jobId);
    if (!metadata || metadata.status !== 'complete') continue;

    const fileId = metadata.file_id;
    if (!fileId) continue;

    const title = metadata.book_title || 'Unknown';
    const completedDate = metadata.completed_at ? new Date(metadata.completed_at) : new Date();

    if (fileIdMap.has(fileId)) {
      // Update existing row
      const rowIndex = fileIdMap.get(fileId);
      updateRowInSheet(sheet, rowIndex, metadata, completedDate);
    } else {
      // Append new row
      appendJobToSheet(sheet, jobId, metadata);
      syncedCount++;
      console.log(`Newly synced: ${title}`);
    }
  }
  
  console.log(`Sync complete. New entries added: ${syncedCount}`);
  return syncedCount;
}

/**
 * Lists metadata.json objects updated within the last N hours.
 * Much faster than listing all folders individually.
 */
function listRecentMetadataObjects(hours) {
  const CONFIG = getGcsConfig_();  // Load config
  const accessToken = ScriptApp.getOAuthToken();
  const url = `https://storage.googleapis.com/storage/v1/b/${CONFIG.GCS_BUCKET}/o?prefix=${CONFIG.JOBS_PREFIX}`;
  
  const response = UrlFetchApp.fetch(url, {
    headers: { 'Authorization': `Bearer ${accessToken}` },
    muteHttpExceptions: true
  });
  
  if (response.getResponseCode() !== 200) {
    console.error('Failed to list GCS objects:', response.getContentText());
    return [];
  }
  
  const data = JSON.parse(response.getContentText());
  const items = data.items || [];
  const cutoff = new Date(Date.now() - hours * 60 * 60 * 1000);
  
  return items.filter(obj => {
    // Only target metadata.json files modified after the cutoff
    return obj.name.endsWith('metadata.json') && new Date(obj.updated) > cutoff;
  });
}

/**
 * Helper to update an existing row in the log sheet.
 */
function updateRowInSheet(sheet, rowIndex, metadata, completedDate) {
  // Column D: Processed Date
  sheet.getRange(rowIndex, 4).setValue(completedDate);
  // Column E: Generated Title
  sheet.getRange(rowIndex, 5).setValue(metadata.book_title || 'Unknown');
  // Column F: Author
  if (metadata.author) sheet.getRange(rowIndex, 6).setValue(metadata.author);
  // Column G: Concepts
  if (metadata.concepts) sheet.getRange(rowIndex, 7).setValue(metadata.concepts.join(', '));
  // Column H: New Concepts
  if (metadata.newConcepts) sheet.getRange(rowIndex, 8).setValue(metadata.newConcepts.join(', '));
  // Column I: GCS URI
  if (metadata.output_uri) sheet.getRange(rowIndex, 9).setValue(metadata.output_uri);
}


/**
 * Reads job metadata.json from GCS.
 */
function readJobMetadata(jobId) {
  const CONFIG = getGcsConfig_();  // Load config
  const accessToken = ScriptApp.getOAuthToken();
  const objectPath = `jobs/${jobId}/metadata.json`;
  const url = `https://storage.googleapis.com/storage/v1/b/${CONFIG.GCS_BUCKET}/o/${encodeURIComponent(objectPath)}?alt=media`;
  
  const response = UrlFetchApp.fetch(url, {
    headers: { 'Authorization': `Bearer ${accessToken}` },
    muteHttpExceptions: true
  });
  
  if (response.getResponseCode() !== 200) {
    return null;
  }
  
  try {
    return JSON.parse(response.getContentText());
  } catch (e) {
    console.error(`Failed to parse metadata for job ${jobId}:`, e);
    return null;
  }
}

/**
 * Gets a map of File IDs to Row Indexes.
 */
function getFileIdMap(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow <= 1) return new Map();
  
  const data = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
  const map = new Map();
  
  data.forEach((row, index) => {
    const fileId = row[0];
    if (fileId) {
      // Row index is index + 2 (header is row 1, data starts row 2)
      map.set(fileId, index + 2);
    }
  });
  
  return map;
}

/**
 * Appends a completed job to the spreadsheet.
 */
function appendJobToSheet(sheet, jobId, metadata) {
  // Extract book title
  const title = metadata.book_title || 'Unknown';
  
  const row = [
    metadata.file_id || jobId,           // A: File ID
    title,                               // B: File Name
    metadata.category || 'Business',     // C: Category
    metadata.completed_at ? new Date(metadata.completed_at) : new Date(), // D: Processed Date
    title,                               // E: Generated Title
    metadata.author || '',               // F: Author
    (metadata.concepts || []).join(', '),// G: Concepts
    (metadata.newConcepts || []).join(', '), // H: New Concepts
    metadata.output_uri || ''            // I: GCS URI
  ];
  
  sheet.appendRow(row);
}

/**
 * Sets up automatic sync trigger (every 30 minutes).
 */
function setupSyncTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(t => {
    if (t.getHandlerFunction() === 'syncCompletedJobs') {
      ScriptApp.deleteTrigger(t);
    }
  });
  
  ScriptApp.newTrigger('syncCompletedJobs')
    .timeBased()
    .atHour(2) // Runs between 2:00 and 3:00 AM
    .everyDays(1)
    .create();
    
  console.log('Sync trigger set up: syncCompletedJobs daily at 2 AM.');
}

/**
 * Manual test function.
 */
function testSync() {
  const count = syncCompletedJobs();
  console.log(`Test sync completed. Synced ${count} jobs.`);
}
