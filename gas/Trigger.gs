/**
 * Book Summary System - Trigger Script
 * Monitors specific folders for new PDF files and triggers the Cloud Function.
 */

// === Configuration ===
// === Configuration ===
// These values are now fetched from Script Properties for security.
// Use setInitialProperties() to initialize these if needed.
const props = PropertiesService.getScriptProperties();
const CONFIG = {
  // Map of Category Name to Folder ID (parsed from JSON string in properties)
  SOURCE_FOLDERS: JSON.parse(props.getProperty('SOURCE_FOLDERS') || '{}'),
  
  // URL of your deployed Cloud Function
  CLOUD_FUNCTION_URL: props.getProperty('CLOUD_FUNCTION_URL') || '',
  
  // Spreadsheet ID to track processed files
  PROCESSED_SHEET_ID: props.getProperty('PROCESSED_SHEET_ID') || '',
  
  // Sheet Name for logging
  LOG_SHEET_NAME: props.getProperty('LOG_SHEET_NAME') || 'log'
};


// === Main Trigger Function ===
function checkNewFiles() {
  const processedIds = getProcessedFileIds();
  
  for (const [category, folderId] of Object.entries(CONFIG.SOURCE_FOLDERS)) {
    try {
      const folder = DriveApp.getFolderById(folderId);
      const files = folder.getFilesByType(MimeType.PDF);
      
      while (files.hasNext()) {
        const file = files.next();
        const fileId = file.getId();
        
        if (processedIds.has(fileId)) continue;
        
        console.log(`Processing new file: ${file.getName()} (${category})`);
        
        try {
          const result = callCloudFunction(fileId, category);
          
          if (result && !result.error && (result.status === 'success' || result.status === 'queued')) {
            // Cloud Function now writes directly to GCS or queues to Cloud Tasks
            // GAS only logs the result
            
            const logData = {
              title: result.metadata?.title || result.job_id || file.getName(),
              author: result.metadata?.author || 'Processing...',
              concepts: result.metadata?.concepts || [],
              new_concepts: result.metadata?.newConcepts || [],
              gcs_uri: result.gcs_uri || `Queued: ${result.chapters || 0} chapters`
            };
            
            markAsProcessed(fileId, file.getName(), category, logData);
            
            if (result.status === 'queued') {
              console.log(`  -> Queued: ${result.chapters} chapters, Job ID: ${result.job_id}`);
            } else {
              console.log(`  -> Success: ${logData.title}`);
              console.log(`  -> GCS URI: ${logData.gcs_uri}`);
            }
            
          } else {
             console.error(`  -> Cloud Function Error: ${JSON.stringify(result)}`);
          }
        } catch (e) {
          console.error(`Error processing ${file.getName()}: ${e}`);
          console.error(e.stack);
        }
      }
    } catch (e) {
      console.error(`Error accessing folder for ${category}: ${e}`);
    }
  }
}

function callCloudFunction(fileId, category) {
  const payload = {
    file_id: fileId,
    category: category
  };
  
  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };
  
  const response = UrlFetchApp.fetch(CONFIG.CLOUD_FUNCTION_URL, options);
  const responseCode = response.getResponseCode();
  const contentText = response.getContentText();
  
  try {
    return JSON.parse(contentText);
  } catch (e) {
    return { error: `Invalid JSON response (${responseCode}): ${contentText}` };
  }
}

// === File & Index Management Helpers ===
// (REMOVED: createMarkdownFile, updateBooksIndex, updateConceptsIndex, appendToIndexFile)
// These are now handled by Cloud Function writing directly to GCS


// === Spreadsheet Helpers ===

function getProcessedFileIds() {
  const sheet = getLogSheet();
  const lastRow = sheet.getLastRow();
  
  if (lastRow <= 1) return new Set();
  
  // Assuming Column A (Index 0) holds File IDs
  // Data starts from Row 2
  const data = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
  // Flatten and create Set
  return new Set(data.map(row => row[0]));
}

function markAsProcessed(fileId, fileName, category, result) {
  const sheet = getLogSheet();
  sheet.appendRow([
    fileId,
    fileName,
    category,
    new Date(), // Timestamp
    result.title || '',
    result.author || '',
    (result.concepts || []).join(', '),
    (result.new_concepts || []).join(', '),
    result.gcs_uri || ''
  ]);
}

function getLogSheet() {
  const ss = SpreadsheetApp.openById(CONFIG.PROCESSED_SHEET_ID);
  let sheet = ss.getSheetByName(CONFIG.LOG_SHEET_NAME);
  
  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.LOG_SHEET_NAME);
    // Initialize Headers
    sheet.appendRow([
      'File ID', 'File Name', 'Category', 'Processed Date', 
      'Generated Title', 'Author', 'Concepts', 'New Concepts', 'GCS URI'
    ]);
  }
  return sheet;
}

// === Auto-Setup Trigger ===
function setupTrigger() {
  // Clear existing triggers to avoid duplicates
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(t => ScriptApp.deleteTrigger(t));
  
  ScriptApp.newTrigger('checkNewFiles')
    .timeBased()
    .atHour(1) // Runs between 1:00 and 2:00 AM
    .everyDays(1)
    .create();
    
  console.log('Trigger set up: checkNewFiles daily at 1 AM.');
}
