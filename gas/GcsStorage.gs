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
 * Deduplicates by file_id to show only the most recent job per book.
 */
function syncCompletedJobs() {
  const sheet = getLogSheet();
  const fileIdMap = getFileIdMap(sheet);
  
  // Get metadata files updated in the last 72 hours (3 days)
  const recentMetadataObjects = listRecentMetadataObjects(72);
  console.log(`Found ${recentMetadataObjects.length} recently updated metadata files in GCS`);
  
  // Deduplicate by file_id, keeping only the most recent job per book
  const uniqueJobs = deduplicateJobsByFileId(recentMetadataObjects);
  console.log(`Unique files after deduplication: ${uniqueJobs.length}`);
  
  // Status tracking
  const statusCounts = { complete: 0, completed: 0, processing: 0, failed: 0, queued: 0, unknown: 0 };
  const processingJobs = [];
  const failedJobs = [];
  
  let syncedCount = 0;
  let updatedCount = 0;
  
  for (const { obj, metadata, jobId } of uniqueJobs) {
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
  console.log(`Total unique files: ${uniqueJobs.length}`);
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
 * Deduplicates jobs by file_id, keeping only the most recent job for each file.
 * Returns array of { obj, metadata, jobId } sorted by updated timestamp.
 */
function deduplicateJobsByFileId(metadataObjects) {
  const jobsByFileId = new Map();
  
  for (const obj of metadataObjects) {
    const pathParts = obj.name.split('/');
    if (pathParts.length < 2) continue;
    const jobId = pathParts[1];
    
    const metadata = readJobMetadata(jobId);
    if (!metadata) continue;
    
    const fileId = metadata.file_id;
    if (!fileId) continue;
    
    const updatedAt = new Date(obj.updated);
    
    // Keep only the most recent job per file_id
    if (!jobsByFileId.has(fileId) || jobsByFileId.get(fileId).updatedAt < updatedAt) {
      jobsByFileId.set(fileId, { obj, metadata, jobId, updatedAt });
    }
  }
  
  return Array.from(jobsByFileId.values());
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

// === Job Cleanup Functions ===

/**
 * Cleans up old job folders from GCS.
 * - Completed jobs: deleted after 7 days
 * - Failed jobs: deleted after 3 days
 * 
 * Run manually or set up as a weekly trigger.
 */
function cleanupOldJobs() {
  const CONFIG = getGcsConfig_();
  const accessToken = ScriptApp.getOAuthToken();
  
  console.log('Starting job cleanup...');
  
  // List all objects in jobs/ prefix
  const url = `https://storage.googleapis.com/storage/v1/b/${CONFIG.GCS_BUCKET}/o?prefix=jobs/`;
  const response = UrlFetchApp.fetch(url, {
    headers: { 'Authorization': `Bearer ${accessToken}` },
    muteHttpExceptions: true
  });
  
  if (response.getResponseCode() !== 200) {
    console.error('Failed to list jobs:', response.getContentText());
    return;
  }
  
  const data = JSON.parse(response.getContentText());
  const items = data.items || [];
  
  // Group objects by jobId
  const jobObjects = new Map();
  for (const obj of items) {
    const parts = obj.name.split('/');
    if (parts.length >= 2 && parts[1]) {
      const jobId = parts[1];
      if (!jobObjects.has(jobId)) {
        jobObjects.set(jobId, []);
      }
      jobObjects.get(jobId).push(obj.name);
    }
  }
  
  console.log(`Found ${jobObjects.size} job folders in GCS`);
  
  const now = new Date();
  const COMPLETED_RETENTION_DAYS = 7;
  const FAILED_RETENTION_DAYS = 3;
  
  let deletedCount = 0;
  let skippedCount = 0;
  
  for (const [jobId, objectNames] of jobObjects) {
    const metadata = readJobMetadata(jobId);
    const statusData = readJobStatus(jobId);
    
    if (!metadata) {
      skippedCount++;
      continue;
    }
    
    // Determine status
    const effectiveStatus = (statusData && statusData.status) 
      ? statusData.status 
      : (metadata.status || 'unknown');
    
    // Determine last update time
    let updatedAt = null;
    if (statusData && statusData.updated_at) {
      updatedAt = new Date(statusData.updated_at);
    } else if (metadata.completed_at) {
      updatedAt = new Date(metadata.completed_at);
    } else if (metadata.created_at) {
      updatedAt = new Date(metadata.created_at);
    }
    
    if (!updatedAt) {
      skippedCount++;
      continue;
    }
    
    const daysSinceUpdate = (now - updatedAt) / (1000 * 60 * 60 * 24);
    
    let shouldDelete = false;
    let reason = '';
    
    if ((effectiveStatus === 'complete' || effectiveStatus === 'completed') 
        && daysSinceUpdate > COMPLETED_RETENTION_DAYS) {
      shouldDelete = true;
      reason = `completed ${Math.floor(daysSinceUpdate)} days ago`;
    } else if (effectiveStatus === 'failed' && daysSinceUpdate > FAILED_RETENTION_DAYS) {
      shouldDelete = true;
      reason = `failed ${Math.floor(daysSinceUpdate)} days ago`;
    }
    
    if (shouldDelete) {
      const title = metadata.book_title || jobId;
      console.log(`Deleting: ${title} (${reason})`);
      deleteJobFolder_(objectNames);
      deletedCount++;
    }
  }
  
  console.log('');
  console.log('=== Cleanup Summary ===');
  console.log(`Deleted: ${deletedCount} old job folders`);
  console.log(`Skipped: ${skippedCount} (no metadata or timestamp)`);
  console.log('Cleanup complete.');
}

/**
 * Deletes all objects in a job folder.
 * @private
 */
function deleteJobFolder_(objectNames) {
  const CONFIG = getGcsConfig_();
  const accessToken = ScriptApp.getOAuthToken();
  
  for (const objectName of objectNames) {
    const url = `https://storage.googleapis.com/storage/v1/b/${CONFIG.GCS_BUCKET}/o/${encodeURIComponent(objectName)}`;
    try {
      UrlFetchApp.fetch(url, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${accessToken}` },
        muteHttpExceptions: true
      });
    } catch (e) {
      console.error(`Failed to delete ${objectName}: ${e}`);
    }
  }
}

/**
 * Dry run - shows what would be deleted without actually deleting.
 */
function previewCleanup() {
  const CONFIG = getGcsConfig_();
  const accessToken = ScriptApp.getOAuthToken();
  
  console.log('=== Cleanup Preview (Dry Run) ===');
  console.log('');
  
  const url = `https://storage.googleapis.com/storage/v1/b/${CONFIG.GCS_BUCKET}/o?prefix=jobs/`;
  const response = UrlFetchApp.fetch(url, {
    headers: { 'Authorization': `Bearer ${accessToken}` },
    muteHttpExceptions: true
  });
  
  if (response.getResponseCode() !== 200) {
    console.error('Failed to list jobs');
    return;
  }
  
  const data = JSON.parse(response.getContentText());
  const items = data.items || [];
  
  // Extract unique job IDs
  const jobIds = new Set();
  for (const obj of items) {
    const parts = obj.name.split('/');
    if (parts.length >= 2 && parts[1]) {
      jobIds.add(parts[1]);
    }
  }
  
  const now = new Date();
  const toDelete = [];
  const toKeep = [];
  
  for (const jobId of jobIds) {
    const metadata = readJobMetadata(jobId);
    const statusData = readJobStatus(jobId);
    
    if (!metadata) continue;
    
    const effectiveStatus = (statusData && statusData.status) 
      ? statusData.status 
      : (metadata.status || 'unknown');
    
    let updatedAt = null;
    if (statusData && statusData.updated_at) {
      updatedAt = new Date(statusData.updated_at);
    } else if (metadata.completed_at) {
      updatedAt = new Date(metadata.completed_at);
    }
    
    if (!updatedAt) continue;
    
    const daysSinceUpdate = (now - updatedAt) / (1000 * 60 * 60 * 24);
    const title = metadata.book_title || jobId;
    
    if ((effectiveStatus === 'complete' || effectiveStatus === 'completed') && daysSinceUpdate > 7) {
      toDelete.push(`${title} (${effectiveStatus}, ${Math.floor(daysSinceUpdate)}d)`);
    } else if (effectiveStatus === 'failed' && daysSinceUpdate > 3) {
      toDelete.push(`${title} (${effectiveStatus}, ${Math.floor(daysSinceUpdate)}d)`);
    } else {
      toKeep.push(`${title} (${effectiveStatus}, ${Math.floor(daysSinceUpdate)}d)`);
    }
  }
  
  console.log('Would DELETE:');
  if (toDelete.length === 0) {
    console.log('  (none)');
  } else {
    for (const item of toDelete) {
      console.log(`  - ${item}`);
    }
  }
  
  console.log('');
  console.log('Would KEEP:');
  for (const item of toKeep) {
    console.log(`  - ${item}`);
  }
  
  console.log('');
  console.log(`Summary: ${toDelete.length} to delete, ${toKeep.length} to keep`);
}
