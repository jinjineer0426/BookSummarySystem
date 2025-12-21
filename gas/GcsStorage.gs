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
 * Enhanced to provide detailed status reporting for all jobs.
 */
function syncCompletedJobs() {
  const sheet = getLogSheet();
  const fileIdMap = getFileIdMap(sheet);
  
  // Get metadata files updated in the last 72 hours (3 days)
  const recentMetadataObjects = listRecentMetadataObjects(72);
  console.log(`Found ${recentMetadataObjects.length} recently updated metadata files in GCS`);
  
  // Status tracking
  const statusCounts = { complete: 0, completed: 0, processing: 0, failed: 0, queued: 0, unknown: 0 };
  const processingJobs = [];
  const failedJobs = [];
  
  let syncedCount = 0;
  let updatedCount = 0;
  
  for (const obj of recentMetadataObjects) {
    const pathParts = obj.name.split('/');
    if (pathParts.length < 2) continue;
    const jobId = pathParts[1];
    
    const metadata = readJobMetadata(jobId);
    if (!metadata) continue;
    
    // Read status.json for detailed progress (may not exist)
    const statusData = readJobStatus(jobId);
    
    // Determine effective status (status.json is more accurate if exists)
    let effectiveStatus = 'unknown';
    if (statusData && statusData.status) {
      effectiveStatus = statusData.status;
    } else if (metadata.status) {
      effectiveStatus = metadata.status;
    }
    
    // Count by status
    if (statusCounts.hasOwnProperty(effectiveStatus)) {
      statusCounts[effectiveStatus]++;
    } else {
      statusCounts.unknown++;
    }
    
    // Track processing/queued jobs with progress
    if (effectiveStatus === 'processing' || effectiveStatus === 'queued') {
      const bookTitle = metadata.book_title || 'Unknown';
      const totalChapters = metadata.total_chapters || 0;
      const completedChapters = Array.isArray(metadata.completed_chapters) 
        ? metadata.completed_chapters.length 
        : 0;
      
      let progressStr = '';
      if (statusData && statusData.details && statusData.details.progress) {
        progressStr = statusData.details.progress;
      } else if (totalChapters > 0) {
        progressStr = `${completedChapters}/${totalChapters}`;
      }
      
      processingJobs.push({
        title: bookTitle,
        status: effectiveStatus,
        progress: progressStr,
        stage: (statusData && statusData.details) ? statusData.details.stage : ''
      });
    }
    
    // Track failed jobs
    if (effectiveStatus === 'failed') {
      const errorMsg = (statusData && statusData.details && statusData.details.error) 
        ? statusData.details.error 
        : 'Unknown error';
      failedJobs.push({
        title: metadata.book_title || 'Unknown',
        error: errorMsg
      });
    }
    
    // Sync logic for complete jobs only
    if (metadata.status !== 'complete' && effectiveStatus !== 'completed') continue;
    
    const fileId = metadata.file_id;
    if (!fileId) continue;

    const title = metadata.book_title || 'Unknown';
    const completedDate = metadata.completed_at ? new Date(metadata.completed_at) : new Date();

    if (fileIdMap.has(fileId)) {
      const rowIndex = fileIdMap.get(fileId);
      updateRowInSheet(sheet, rowIndex, metadata, completedDate);
      updatedCount++;
    } else {
      appendJobToSheet(sheet, jobId, metadata);
      syncedCount++;
      console.log(`Newly synced: ${title}`);
    }
  }
  
  // Enhanced output
  console.log('');
  console.log('=== Job Status Report ===');
  console.log(`Total jobs checked: ${recentMetadataObjects.length}`);
  console.log('');
  console.log('Status breakdown:');
  console.log(`  ✓ Complete: ${statusCounts.complete + statusCounts.completed}`);
  console.log(`  ⏳ Processing: ${statusCounts.processing}`);
  console.log(`  📋 Queued: ${statusCounts.queued}`);
  console.log(`  ✗ Failed: ${statusCounts.failed}`);
  if (statusCounts.unknown > 0) {
    console.log(`  ? Unknown: ${statusCounts.unknown}`);
  }
  
  if (processingJobs.length > 0) {
    console.log('');
    console.log('Processing/Queued jobs:');
    for (const job of processingJobs) {
      const progressPart = job.progress ? ` (${job.progress})` : '';
      const stagePart = job.stage ? ` - ${job.stage}` : '';
      console.log(`  - ${job.title}${progressPart}${stagePart}`);
    }
  }
  
  if (failedJobs.length > 0) {
    console.log('');
    console.log('Failed jobs:');
    for (const job of failedJobs) {
      const truncatedError = job.error.length > 50 ? job.error.substring(0, 50) + '...' : job.error;
      console.log(`  - ${job.title}: ${truncatedError}`);
    }
  }
  
  console.log('');
  console.log('Sync results:');
  console.log(`  New entries added: ${syncedCount}`);
  console.log(`  Existing entries updated: ${updatedCount}`);
  console.log('');
  console.log('Sync complete.');
  
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
 * Reads job status.json from GCS for detailed progress tracking.
 * Returns null if status.json doesn't exist (older jobs may not have it).
 */
function readJobStatus(jobId) {
  const CONFIG = getGcsConfig_();
  const accessToken = ScriptApp.getOAuthToken();
  const objectPath = `jobs/${jobId}/status.json`;
  const url = `https://storage.googleapis.com/storage/v1/b/${CONFIG.GCS_BUCKET}/o/${encodeURIComponent(objectPath)}?alt=media`;
  
  const response = UrlFetchApp.fetch(url, {
    headers: { 'Authorization': `Bearer ${accessToken}` },
    muteHttpExceptions: true
  });
  
  if (response.getResponseCode() !== 200) {
    return null;  // status.json doesn't exist for this job
  }
  
  try {
    return JSON.parse(response.getContentText());
  } catch (e) {
    console.error(`Failed to parse status.json for job ${jobId}:`, e);
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
