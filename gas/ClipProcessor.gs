/**
 * Clip Processor Module
 * Processes web article clips from Google Drive Inbox folder,
 * extracts concepts using Gemini, and creates Obsidian-compatible links.
 */

// === Configuration (Unified via ConfigService) ===
/**
 * Get clip processor configuration from ConfigService
 */
function getClipConfig_() {
  const config = new ConfigService().getConfig();
  const props = PropertiesService.getScriptProperties();
  const clipConfig = config.clip_processor || {};
  
  return {
    // Google Drive Inbox Folder
    INBOX_FOLDER_ID: clipConfig.inbox_folder_id || '1IEnNn2Fp0nK_QN19DX080FRppc0h4Zsy',
    
    // Cloud Function URL for clip processing (future use)
    CLIP_PROCESSOR_URL: clipConfig.processor_url || '',
    
    // GCS paths for output
    GCS_BUCKET: clipConfig.gcs_bucket || 'obsidian_vault_sync_my_knowledge',
    GCS_PATHS: clipConfig.gcs_paths || {
      INBOX: '10_Inbox/',
      READING: '20_Reading/',
      KNOWLEDGE: '30_Knowledge/'
    },
    
    // Spreadsheet for tracking processed clips
    PROCESSED_SHEET_ID: clipConfig.processed_sheet_id || '18Atya7cL1QN6NNo1mgisUKLsgJ6aj4pzBsrBp-zZPmQ',
    CLIP_LOG_SHEET_NAME: clipConfig.clip_log_sheet_name || 'clip_log',
    
    // Gemini API Key (from Script Properties for security)
    GEMINI_API_KEY: props.getProperty('GEMINI_API_KEY') || ''
  };
}

// === Main Functions ===

/**
 * Checks for new clips in the Inbox folder and processes them
 * Called by time-based trigger
 */
function checkNewClips() {
  const CLIP_CONFIG = getClipConfig_();  // Load config
  const processedIds = getProcessedClipIds();
  
  try {
    const folder = DriveApp.getFolderById(CLIP_CONFIG.INBOX_FOLDER_ID);
    const files = folder.getFilesByType(MimeType.PLAIN_TEXT);
    
    let processedCount = 0;
    
    while (files.hasNext()) {
      const file = files.next();
      const fileId = file.getId();
      const fileName = file.getName();
      
      // Skip if not a markdown file
      if (!fileName.endsWith('.md')) continue;
      
      // Skip if already processed
      if (processedIds.has(fileId)) continue;
      
      console.log(`Processing clip: ${fileName}`);
      
      try {
        const result = processClip(fileId);
        
        if (result.success) {
          markClipAsProcessed(fileId, fileName, result);
          processedCount++;
          console.log(`  -> Success: extracted ${result.concepts.length} concepts`);
        } else {
          console.error(`  -> Failed: ${result.error}`);
        }
      } catch (e) {
        console.error(`Error processing ${fileName}: ${e}`);
        console.error(e.stack);
      }
    }
    
    console.log(`Processed ${processedCount} new clips`);
    
  } catch (e) {
    console.error(`Error accessing Inbox folder: ${e}`);
  }
}

/**
 * Batch process all existing clips (for migration from Notion/Evernote)
 * Reprocesses all clips, ignoring the processed list
 * @param {boolean} force - If true, reprocess even already processed clips
 */
function batchProcessExistingClips(force = true) {
  const CLIP_CONFIG = getClipConfig_();  // Load config
  const processedIds = force ? new Set() : getProcessedClipIds();
  
  try {
    const folder = DriveApp.getFolderById(CLIP_CONFIG.INBOX_FOLDER_ID);
    const files = folder.getFilesByType(MimeType.PLAIN_TEXT);
    
    let total = 0;
    let success = 0;
    let failed = 0;
    
    while (files.hasNext()) {
      const file = files.next();
      const fileId = file.getId();
      const fileName = file.getName();
      
      if (!fileName.endsWith('.md')) continue;
      if (processedIds.has(fileId)) continue;
      
      total++;
      console.log(`[${total}] Processing: ${fileName}`);
      
      try {
        const result = processClip(fileId);
        
        if (result.success) {
          markClipAsProcessed(fileId, fileName, result);
          success++;
          console.log(`  -> Success`);
        } else {
          failed++;
          console.error(`  -> Failed: ${result.error}`);
        }
        
        // Rate limiting - wait between API calls
        Utilities.sleep(1000);
        
      } catch (e) {
        failed++;
        console.error(`  -> Error: ${e}`);
      }
    }
    
    console.log(`\n=== Batch Complete ===`);
    console.log(`Total: ${total}, Success: ${success}, Failed: ${failed}`);
    
  } catch (e) {
    console.error(`Batch process error: ${e}`);
  }
}

/**
 * Processes a single clip file
 * @param {string} fileId - Google Drive file ID
 * @returns {Object} Processing result
 */
function processClip(fileId) {
  const CLIP_CONFIG = getClipConfig_();  // Load config
  
  // 1. Read clip content from Drive
  const file = DriveApp.getFileById(fileId);
  const content = file.getBlob().getDataAsString('UTF-8');
  const fileName = file.getName();
  
  // 2. Parse YAML frontmatter and content
  const parsed = parseClipContent(content);
  
  // 3. Extract concepts using Gemini
  const extraction = extractConceptsWithGemini(parsed.content, parsed.metadata);
  
  if (!extraction.success) {
    return {
      success: false,
      error: extraction.error
    };
  }
  
  // 4. Match concepts with existing master list
  const matchedConcepts = matchWithMasterConcepts(extraction.concepts);
  
  // 5. Find related books from index
  const relatedBooks = findRelatedBooks(matchedConcepts);
  
  // 6. Enhance clip with wiki links
  const enhancedContent = enhanceClipWithLinks(
    content,
    matchedConcepts,
    relatedBooks,
    extraction.summary
  );
  
  // 7. Upload enhanced clip to GCS
  const gcsPath = `${CLIP_CONFIG.GCS_PATHS.INBOX}${fileName}`;
  const uploadResult = uploadToGcs(CLIP_CONFIG.GCS_BUCKET, gcsPath, enhancedContent);
  
  if (!uploadResult.success) {
    return {
      success: false,
      error: `GCS upload failed: ${uploadResult.error}`
    };
  }
  
  // 8. Update Concepts Index
  updateConceptsIndexWithClip(matchedConcepts, parsed.metadata.title || fileName);
  
  // 9. Cleanup: Move original Drive file to trash
  // Only done if everything above succeeded
  try {
    file.setTrashed(true);
    console.log(`  -> Moved to trash: ${fileName}`);
  } catch (e) {
    console.warn(`  -> Failed to trash file: ${e}`);
    // Non-critical error, continue
  }
  
  return {
    success: true,
    concepts: matchedConcepts,
    relatedBooks: relatedBooks,
    gcsPath: gcsPath,
    summary: extraction.summary
  };
}

// === Helper Functions ===

/**
 * Parses clip content to extract YAML frontmatter and body
 * @param {string} content - Raw markdown content
 * @returns {Object} Parsed metadata and content
 */
function parseClipContent(content) {
  const frontmatterRegex = /^---\n([\s\S]*?)\n---\n([\s\S]*)$/;
  const match = content.match(frontmatterRegex);
  
  if (!match) {
    return {
      metadata: {},
      content: content
    };
  }
  
  const yamlStr = match[1];
  const bodyContent = match[2];
  
  // Simple YAML parsing (key: value)
  const metadata = {};
  const lines = yamlStr.split('\n');
  let currentKey = null;
  
  for (const line of lines) {
    const keyMatch = line.match(/^(\w+):\s*(.*)$/);
    if (keyMatch) {
      currentKey = keyMatch[1];
      let value = keyMatch[2].trim();
      
      // Handle quoted strings
      if (value.startsWith('"') && value.endsWith('"')) {
        value = value.slice(1, -1);
      }
      
      metadata[currentKey] = value;
    }
  }
  
  return {
    metadata: metadata,
    content: bodyContent
  };
}

/**
 * Extracts concepts from clip content using Gemini API
 * @param {string} content - Clip body content
 * @param {Object} metadata - Clip metadata
 * @returns {Object} Extraction result with concepts and summary
 */
function extractConceptsWithGemini(content, metadata) {
  const CLIP_CONFIG = getClipConfig_();  // Load config
  if (!CLIP_CONFIG.GEMINI_API_KEY) {
    return {
      success: false,
      error: 'GEMINI_API_KEY not configured'
    };
  }
  
  const prompt = `
あなたはナレッジマネジメントの専門家です。
以下のWeb記事クリップを分析し、キーコンセプトを抽出してください。

記事タイトル: ${metadata.title || 'Unknown'}
記事URL: ${metadata.source || 'Unknown'}

記事内容:
${content.substring(0, 10000)}

以下のJSON形式で出力してください:
{
  "concepts": ["コンセプト1", "コンセプト2", ...],
  "summary": "3行程度の要約",
  "category": "カテゴリ（ビジネス/技術/人文など）"
}

注意:
- コンセプトは具体的で再利用可能なキーワードにしてください
- 一般的すぎる単語（「情報」「方法」など）は避けてください
- 5〜10個程度のコンセプトを抽出してください
`;

  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key=${CLIP_CONFIG.GEMINI_API_KEY}`;
  
  const payload = {
    contents: [{
      parts: [{ text: prompt }]
    }],
    generationConfig: {
      temperature: 0.2,
      responseMimeType: 'application/json'
    }
  };
  
  try {
    const response = UrlFetchApp.fetch(url, {
      method: 'POST',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
    
    const responseCode = response.getResponseCode();
    if (responseCode !== 200) {
      return {
        success: false,
        error: `Gemini API error (${responseCode}): ${response.getContentText()}`
      };
    }
    
    const result = JSON.parse(response.getContentText());
    const text = result.candidates[0].content.parts[0].text;
    
    // Clean JSON response
    let cleanedText = text.trim();
    if (cleanedText.startsWith('```json')) {
      cleanedText = cleanedText.replace(/^```json\s*/, '').replace(/\s*```$/, '');
    } else if (cleanedText.startsWith('```')) {
      cleanedText = cleanedText.replace(/^```\s*/, '').replace(/\s*```$/, '');
    }
    
    const data = JSON.parse(cleanedText);
    
    return {
      success: true,
      concepts: data.concepts || [],
      summary: data.summary || '',
      category: data.category || 'Other'
    };
    
  } catch (e) {
    return {
      success: false,
      error: `Gemini extraction failed: ${e}`
    };
  }
}

/**
 * Matches extracted concepts with master concept list
 * @param {Array} concepts - Raw concepts from extraction
 * @returns {Array} Matched/normalized concepts
 */
function matchWithMasterConcepts(concepts) {
  const CLIP_CONFIG = getClipConfig_();  // Load config
  // Download master concepts from GCS
  const masterResult = downloadFromGcs(CLIP_CONFIG.GCS_BUCKET, 'config/master_concepts.json');
  
  let masterConcepts = {};
  if (masterResult.success) {
    try {
      const data = JSON.parse(masterResult.content);
      masterConcepts = data.concepts || {};
    } catch (e) {
      console.log('Failed to parse master concepts, using empty list');
    }
  }
  
  const matched = [];
  const masterNames = Object.keys(masterConcepts);
  const masterLower = masterNames.map(n => n.toLowerCase().replace(/[\s-]/g, ''));
  
  for (const concept of concepts) {
    const conceptLower = concept.toLowerCase().replace(/[\s-]/g, '');
    
    // Check exact match with master
    const idx = masterLower.indexOf(conceptLower);
    if (idx !== -1) {
      matched.push(masterNames[idx]);
    } else {
      // Check aliases
      let found = false;
      for (const [name, data] of Object.entries(masterConcepts)) {
        const aliases = (data.aliases || []).map(a => a.toLowerCase().replace(/[\s-]/g, ''));
        if (aliases.includes(conceptLower)) {
          matched.push(name);
          found = true;
          break;
        }
      }
      
      if (!found) {
        // New concept - add as-is
        matched.push(concept);
      }
    }
  }
  
  return [...new Set(matched)]; // Deduplicate
}

/**
 * Finds related books based on concepts
 * @param {Array} concepts - List of concepts
 * @returns {Array} Related book titles
 */
function findRelatedBooks(concepts) {
  const CLIP_CONFIG = getClipConfig_();  // Load config
  // Download concepts index from GCS
  const indexResult = downloadFromGcs(
    CLIP_CONFIG.GCS_BUCKET, 
    `${CLIP_CONFIG.GCS_PATHS.KNOWLEDGE}00_Concepts_Index.md`
  );
  
  if (!indexResult.success) {
    return [];
  }
  
  const relatedBooks = new Set();
  const content = indexResult.content;
  
  for (const concept of concepts) {
    // Look for: - [[Concept]]: [[Book1]], [[Book2]]
    const regex = new RegExp(`-\\s*\\[\\[${escapeRegex(concept)}\\]\\]:\\s*(.+)$`, 'mi');
    const match = content.match(regex);
    
    if (match) {
      // Extract book links from the matched line
      const bookMatches = match[1].matchAll(/\[\[([^\]]+)\]\]/g);
      for (const bookMatch of bookMatches) {
        relatedBooks.add(bookMatch[1]);
      }
    }
  }
  
  return [...relatedBooks];
}

/**
 * Enhances clip content with wiki links
 * @param {string} originalContent - Original clip content
 * @param {Array} concepts - Matched concepts
 * @param {Array} relatedBooks - Related book titles
 * @param {string} summary - AI-generated summary
 * @returns {string} Enhanced markdown content
 */
function enhanceClipWithLinks(originalContent, concepts, relatedBooks, summary) {
  // Check if already enhanced
  if (originalContent.includes('## Auto-Generated Links')) {
    // Update existing section
    const beforeAuto = originalContent.split('## Auto-Generated Links')[0];
    return beforeAuto + generateLinksSection(concepts, relatedBooks, summary);
  }
  
  // Append new section
  return originalContent + '\n\n' + generateLinksSection(concepts, relatedBooks, summary);
}

/**
 * Generates the auto-links section
 */
function generateLinksSection(concepts, relatedBooks, summary) {
  let section = `---

## Auto-Generated Links

### Summary
${summary}

### Key Concepts
`;

  for (const concept of concepts) {
    section += `- [[${concept}]]\n`;
  }
  
  if (relatedBooks.length > 0) {
    section += `\n### Related Books\n`;
    for (const book of relatedBooks) {
      section += `- [[${book}]]\n`;
    }
  }
  
  return section;
}

/**
 * Updates the Concepts Index with clip references
 * @param {Array} concepts - Concepts to add
 * @param {string} clipTitle - Clip title for reference
 */
function updateConceptsIndexWithClip(concepts, clipTitle) {
  const CLIP_CONFIG = getClipConfig_();  // Load config
  const indexPath = `${CLIP_CONFIG.GCS_PATHS.KNOWLEDGE}00_Concepts_Index.md`;
  
  // Download existing index
  const result = downloadFromGcs(CLIP_CONFIG.GCS_BUCKET, indexPath);
  
  let content = '# Concepts Index\n\n';
  if (result.success) {
    content = result.content;
  }
  
  // Parse existing lines
  const lines = content.split('\n');
  const conceptLineMap = {};
  
  lines.forEach((line, idx) => {
    const match = line.match(/^- \[\[(.+?)\]\]:/);
    if (match) {
      conceptLineMap[match[1]] = idx;
    }
  });
  
  // Add/update concepts
  let updated = false;
  const link = `[[${clipTitle}]]`;
  
  for (const concept of concepts) {
    if (conceptLineMap.hasOwnProperty(concept)) {
      const idx = conceptLineMap[concept];
      if (!lines[idx].includes(link)) {
        lines[idx] += `, ${link}`;
        updated = true;
      }
    } else {
      lines.push(`- [[${concept}]]: ${link}`);
      updated = true;
    }
  }
  
  if (updated) {
    uploadToGcs(CLIP_CONFIG.GCS_BUCKET, indexPath, lines.join('\n'));
  }
}

// === Tracking Functions ===

/**
 * Gets set of already processed clip IDs
 * @returns {Set} Set of file IDs
 */
function getProcessedClipIds() {
  try {
    const sheet = getClipLogSheet();
    const lastRow = sheet.getLastRow();
    
    if (lastRow <= 1) return new Set();
    
    const data = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
    return new Set(data.map(row => row[0]));
  } catch (e) {
    console.error('Error getting processed clips:', e);
    return new Set();
  }
}

/**
 * Marks a clip as processed in the log sheet
 */
function markClipAsProcessed(fileId, fileName, result) {
  const sheet = getClipLogSheet();
  sheet.appendRow([
    fileId,
    fileName,
    new Date(),
    (result.concepts || []).join(', '),
    (result.relatedBooks || []).join(', '),
    result.gcsPath || ''
  ]);
}

/**
 * Gets or creates the clip log sheet
 */
function getClipLogSheet() {
  const CLIP_CONFIG = getClipConfig_();  // Load config
  const ss = SpreadsheetApp.openById(CLIP_CONFIG.PROCESSED_SHEET_ID);
  let sheet = ss.getSheetByName(CLIP_CONFIG.CLIP_LOG_SHEET_NAME);
  
  if (!sheet) {
    sheet = ss.insertSheet(CLIP_CONFIG.CLIP_LOG_SHEET_NAME);
    sheet.appendRow([
      'File ID', 'File Name', 'Processed Date', 
      'Concepts', 'Related Books', 'GCS Path'
    ]);
  }
  
  return sheet;
}

// === Utility Functions ===

/**
 * Escapes special regex characters
 */
function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// === Trigger Setup ===

/**
 * Sets up time-based trigger for clip monitoring
 */
function setupClipTrigger() {
  // Check if trigger already exists
  const triggers = ScriptApp.getProjectTriggers();
  const hasClipTrigger = triggers.some(t => 
    t.getHandlerFunction() === 'checkNewClips'
  );
  
  if (!hasClipTrigger) {
    ScriptApp.newTrigger('checkNewClips')
      .timeBased()
      .everyMinutes(10)
      .create();
    console.log('Clip trigger created: checkNewClips every 10 minutes');
  } else {
    console.log('Clip trigger already exists');
  }
}

/**
 * Removes the clip trigger
 */
function removeClipTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(t => {
    if (t.getHandlerFunction() === 'checkNewClips') {
      ScriptApp.deleteTrigger(t);
      console.log('Clip trigger removed');
    }
  });
}
