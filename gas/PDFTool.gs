/**
 * Google Drive統合版 - ScanSnap PDF結合ツール
 * スタンドアロン・スクリプト版 v2
 * 機能: 表紙・本紙の自動結合、サフィックス対応、表紙の左90度回転
 */

// PDF-Libのロード
// グローバルスコープで定義しておくと安心
let PDFLib = null;

// Gemini Configuration
const pdfProps = PropertiesService.getScriptProperties();
const GEMINI_CONFIG = {
  MODEL_ID: 'gemini-2.0-flash',
  DESTINATION_FOLDER_IDS: JSON.parse(pdfProps.getProperty('PDF_DESTINATION_FOLDERS') || '{}')
};


function loadPdfLib() {
  if (PDFLib) return;
  
  // GAS environment polyfills for browser APIs expected by libraries
  globalThis.setTimeout = function(func, delay) { return func(); };
  globalThis.clearTimeout = function(id) {};
  globalThis.setInterval = function(func, delay) { return func(); };
  globalThis.clearInterval = function(id) {};
  
  const url = "https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.min.js";
  eval(UrlFetchApp.fetch(url).getContentText());
  PDFLib = globalThis.PDFLib;
}

async function main() {
  console.log('処理を開始します...');
  loadPdfLib();
  
  if (!PDFLib) {
    console.error('PDFライブラリのロードに失敗しました。');
    return;
  }
  
  try {
    // ユーザー指定のフォルダを使用 (Fetch from properties)
    const targetFolderId = pdfProps.getProperty('PDF_SCAN_RAW_FOLDER_ID');
    console.log('対象フォルダID: ' + targetFolderId);
    const currentFolder = DriveApp.getFolderById(targetFolderId);
    console.log('対象フォルダ: ' + currentFolder.getName());
    
    // 1. PDF収集
    // getFilesByType('application/pdf') だとMIMEタイプが微妙に異なるファイルを逃す可能性があるため、
    // 全ファイルをスキャンして拡張子またはMIMEタイプで判定する
    const files = currentFolder.getFiles();
    const pdfList = [];
    console.log('PDFファイルをスキャン中...');
    
    while (files.hasNext()) {
      const f = files.next();
      const name = f.getName();
      const mime = f.getMimeType();
      
      console.log(`  File check: ${name} (${mime})`);
      
      if (mime === MimeType.PDF || name.toLowerCase().endsWith('.pdf')) {
        pdfList.push({
          id: f.getId(),
          name: name,
          size: f.getSize(),
          blob: null 
        });
      }
    }
    console.log('検出されたPDFファイル数: ' + pdfList.length + '件');
    
    // 2. 分類とペア作成
    const pairing = classifyAndPairPdfs(pdfList);
    const totalItems = pairing.pairs.length + pairing.standalones.length;
    console.log(`検出: ペア ${pairing.pairs.length}件, スタンドアロン ${pairing.standalones.length}件`);
    
    if (totalItems === 0) {
      console.log('処理可能なファイルが見つかりませんでした。終了します。');
      return;
    }
    
    // 3. 結合処理
    const fallbackFolderId = pdfProps.getProperty('PDF_FALLBACK_FOLDER_ID');
    const fallbackFolder = DriveApp.getFolderById(fallbackFolderId);
    console.log('AI分析スキップ時の保存先: ' + fallbackFolder.getName());
    
    let successCount = 0;
    
    // API Key for Gemini (Script Properties serve as Environment Variables in GAS)
    const scriptProperties = PropertiesService.getScriptProperties();
    const apiKey = scriptProperties.getProperty('GEMINI_API_KEY');
    
    if (!apiKey) {
      console.log('Gemini APIキー (GEMINI_API_KEY) が設定されていません。AI分析をスキップします。');
    }
    
    for (const pair of pairing.pairs) {
      try {
        let combinedName = pair.key; // Default name
        let targetFolderId = fallbackFolder.getId();
        
        console.log(`処理中(ペア): ${pair.name} (表紙: ${pair.cover.name}, 本紙: ${pair.main.name})`);
        
        const coverBytes = downloadBytes(pair.cover.id, pair.cover.size);
        const mainBytes = downloadBytes(pair.main.id, pair.main.size);
        
        if (apiKey) {
           const analysis = analyzePdfWithGemini(coverBytes, apiKey);
           if (analysis) {
             console.log(`  -> AI分析成功: ${JSON.stringify(analysis)}`);
             combinedName = constructFileName(analysis).replace(/\.pdf$/i, '');
             
             const mappedFolderId = GEMINI_CONFIG.DESTINATION_FOLDER_IDS[analysis.category];
             if (mappedFolderId && mappedFolderId.length > 5) {
               targetFolderId = mappedFolderId;
               console.log(`  -> 振分け先: ${analysis.category} (${targetFolderId})`);
             }
           }
        }
        
        const pdfBytes = await mergeAndRotatePdf(coverBytes, mainBytes);
        const outputFileId = saveLargeFile(targetFolderId, combinedName + '.pdf', pdfBytes);
        const outputFile = DriveApp.getFileById(outputFileId);
        outputFile.setDescription(`【自動結合】\n表紙: ${pair.cover.name}\n本紙: ${pair.main.name}`);
        
        successCount++;
        console.log('  -> OK');
        
        DriveApp.getFileById(pair.cover.id).setTrashed(true);
        DriveApp.getFileById(pair.main.id).setTrashed(true);
      } catch (e) {
        console.error('  -> NG: ' + e.message);
      }
    }

    // 4. スタンドアロン処理
    console.log('スタンドアロンファイルの処理を開始します...');
    for (const file of pairing.standalones) {
      try {
        let fileName = file.name.replace(/\.pdf$/i, '');
        let targetFolderId = fallbackFolder.getId();
        
        console.log(`処理中(単体): ${file.name}`);
        
        const fileBytes = downloadBytes(file.id, file.size);
        
        if (apiKey) {
           const analysis = analyzePdfWithGemini(fileBytes, apiKey);
           if (analysis) {
             console.log(`  -> AI分析成功: ${JSON.stringify(analysis)}`);
             fileName = constructFileName(analysis).replace(/\.pdf$/i, '');
             
             const mappedFolderId = GEMINI_CONFIG.DESTINATION_FOLDER_IDS[analysis.category];
             if (mappedFolderId && mappedFolderId.length > 5) {
               targetFolderId = mappedFolderId;
               console.log(`  -> 振分け先: ${analysis.category} (${targetFolderId})`);
             }
           }
        }
        
        // 単体ファイルの場合は回転・結合なしで移動・リネームのみ
        const newFile = DriveApp.getFileById(file.id);
        newFile.setName(fileName + '.pdf');
        
        // フォルダ移動
        const currentParents = newFile.getParents();
        while (currentParents.hasNext()) {
          const parent = currentParents.next();
          parent.removeFile(newFile);
        }
        DriveApp.getFolderById(targetFolderId).addFile(newFile);
        
        newFile.setDescription(`【単体処理】元ファイル名: ${file.name}`);
        
        successCount++;
        console.log('  -> OK');
      } catch (e) {
        console.error('  -> NG: ' + e.message);
      }
    }
    
    console.log('--------------------------------------------------');
    console.log('処理完了: ' + successCount + ' / ' + totalItems + ' 件成功');
    
  } catch (e) {
    console.error('予期せぬエラーが発生しました: ' + e.toString());
  }
}

/**
 * PDFの結合と回転を行う
 */
async function mergeAndRotatePdf(coverBytes, mainBytes) {
  const { PDFDocument, degrees } = PDFLib;
  
  // 新しいドキュメント作成
  const mergedPdf = await PDFDocument.create();
  
  // PDFのロード (Uint8Arrayを直接渡す)
  const coverPdf = await PDFDocument.load(coverBytes);
  const mainPdf = await PDFDocument.load(mainBytes);
  
  // 表紙のコピーと回転 (左に90度 = -90度)
  const coverToCopy = await mergedPdf.copyPages(coverPdf, coverPdf.getPageIndices());
  coverToCopy.forEach(page => {
    const currentRotation = page.getRotation().angle;
    page.setRotation(degrees(currentRotation - 90));
    mergedPdf.addPage(page);
  });
  
  // 本紙のコピー (そのまま)
  const mainToCopy = await mergedPdf.copyPages(mainPdf, mainPdf.getPageIndices());
  mainToCopy.forEach(page => {
    mergedPdf.addPage(page);
  });
  
  // 保存 (Uint8Arrayを返す)
  const savedBytes = await mergedPdf.save();
  return savedBytes;
}

/**
 * 50MBを超えるファイルを保存するためのResumable Upload実装
 */
function saveLargeFile(folderId, fileName, uint8Array) {
  const url = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable';
  const token = ScriptApp.getOAuthToken();
  if (!token) {
    throw new Error('OAuth token is null. Please ensure the script has proper permissions.');
  }
  const size = uint8Array.length;
  
  // 1. セッション開始リクエスト
  const initParams = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'Authorization': 'Bearer ' + token,
      'X-Upload-Content-Type': 'application/pdf',
      'X-Upload-Content-Length': size.toString()
    },
    payload: JSON.stringify({
      name: fileName,
      parents: [folderId],
      mimeType: 'application/pdf'
    })
  };
  
  const initResponse = UrlFetchApp.fetch(url, initParams);
  const uploadUrl = initResponse.getHeaders()['Location'];
  
  // 2. アップロード実行 (チャンク分割なしで一括送信)
  // GASのUrlFetchAppは10MB制限がある場合があるが、まずは一括で試みる。
  // 失敗する場合はここをループ処理にする必要があるが、
  // Blobリミット(50MB)とUrlFetchペイロードリミットは別物。
  // UrlFetchAppのペイロードリミットも50MB程度なので、本当はチャンク分割が必要。
  
  // チャンクサイズ (10MB)
  const CHUNK_SIZE = 10 * 1024 * 1024;
  let offset = 0;
  
  while (offset < size) {
    const isLastChunk = offset + CHUNK_SIZE >= size;
    const chunkEnd = isLastChunk ? size : offset + CHUNK_SIZE;
    const chunk = uint8Array.slice(offset, chunkEnd);
    
    // チャンクをBlobに変換して送信 (Blob生成は小さなサイズならOK)
    const chunkBlob = Utilities.newBlob(chunk);
    
    const uploadParams = {
      method: 'put',
      headers: {
        'Content-Range': `bytes ${offset}-${chunkEnd - 1}/${size}`
      },
      payload: chunkBlob
    };
    
    // エラーハンドリング: 最後以外のレスポンスは308 Resume Incomplete
    try {
      var response = UrlFetchApp.fetch(uploadUrl, uploadParams);
    } catch (e) {
      // 308はGASで例外扱いされる場合があるためキャッチして続行判定
      if (!e.message.includes('308')) {
        throw e;
      }
    }
    
    offset += CHUNK_SIZE;
  }
  
  // 最後のレスポンスからファイルIDを取得
  const result = JSON.parse(response.getContentText());
  return result.id;
}

/**
 * 50MBを超えるファイルを読み込むためのチャンクダウンロード実装
 */
function downloadBytes(fileId, size) {
  const token = ScriptApp.getOAuthToken();
  const url = 'https://www.googleapis.com/drive/v3/files/' + fileId + '?alt=media';
  
  // 50MB以下なら一括でOK (マージンを取って40MBくらいにしておく)
  if (size < 40 * 1024 * 1024) {
    const response = UrlFetchApp.fetch(url, {
      headers: { 'Authorization': 'Bearer ' + token }
    });
    return new Uint8Array(response.getContent());
  }
  
  // 分割ダウンロード
  const combinedBytes = new Uint8Array(size);
  const CHUNK_SIZE = 20 * 1024 * 1024; // 20MB
  let offset = 0;
  
  while (offset < size) {
    const end = Math.min(offset + CHUNK_SIZE - 1, size - 1);
    
    // Rangeリクエスト
    const params = {
      headers: {
        'Authorization': 'Bearer ' + token,
        'Range': 'bytes=' + offset + '-' + end
      },
      muteHttpExceptions: true
    };
    
    const response = UrlFetchApp.fetch(url, params);
    if (response.getResponseCode() !== 206 && response.getResponseCode() !== 200) {
      throw new Error('Download failed: ' + response.getResponseCode() + ' ' + response.getContentText());
    }
    
    const chunkBytes = response.getContent();
    combinedBytes.set(chunkBytes, offset);
    
    offset += CHUNK_SIZE;
  }
  
  return combinedBytes;
}

function classifyAndPairPdfs(pdfList) {
  const covers = {};
  const mains = {};
  const standalones = [];
  
  // 正規表現の定義
  const coverRegex = /^(\d{4})-(\d{2})-(\d{2})(?:_(.+))?\.pdf$/;
  const mainRegex = /^(\d{4})(\d{2})(\d{2})(?:_(.+))?\.pdf$/;
  
  pdfList.forEach(pdf => {
    let match = pdf.name.match(coverRegex);
    if (match) {
      const key = match[1] + match[2] + match[3] + (match[4] ? '_' + match[4] : '');
      covers[key] = pdf;
      return;
    }
    
    match = pdf.name.match(mainRegex);
    if (match) {
      const key = match[1] + match[2] + match[3] + (match[4] ? '_' + match[4] : '');
      mains[key] = pdf;
      return;
    }

    // いずれにもマッチしない場合はスタンドアロン
    standalones.push(pdf);
  });
  
  const pairs = [];
  const processedKeys = new Set();

  Object.keys(mains).forEach(key => {
    if (covers[key]) {
      pairs.push({ 
        key: key, 
        name: key, 
        cover: covers[key], 
        main: mains[key]
      });
      processedKeys.add(key);
    } else {
      // 本紙のみで表紙がない場合もスタンドアロンとして扱う
      standalones.push(mains[key]);
    }
  });

  // 表紙のみで本紙がない場合もスタンドアロンとして扱う
  Object.keys(covers).forEach(key => {
    if (!processedKeys.has(key)) {
      standalones.push(covers[key]);
    }
  });
  
  return { pairs: pairs, standalones: standalones };
}

function getOrCreateFolder(parent, name) {
  const folders = parent.getFoldersByName(name);
  if (folders.hasNext()) {
    return folders.next();
  }
  return parent.createFolder(name);
}

// 互換性のため残す
function identifyPdfType(filename) {
  return 'unknown'; 
}

/**
 * Geminiで表紙PDFを分析する
 * Utilities.newBlobからのgetAsは失敗しやすいため、DriveAppから直接取得する
 */
/**
 * GeminiでPDFを分析する (File APIを使用)
 */
function analyzePdfWithGemini(pdfBytes, apiKey) {
  try {
    // 1. PDF Blobを作成
    const coverBlob = Utilities.newBlob(pdfBytes, 'application/pdf', 'cover.pdf');
    
    // 2. Geminiへアップロード (File API)
    const fileUri = uploadBlobToGemini_(coverBlob, apiKey);
    console.log(`  -> PDFアップロード完了: ${fileUri}`);
    
    // 3. 処理待ち (State: ACTIVEになるまで待機)
    let state = "PROCESSING";
    let attempts = 0;
    while (state === "PROCESSING" && attempts < 10) {
      Utilities.sleep(2000);
      const checkUrl = `https://generativelanguage.googleapis.com/v1beta/files/${fileUri.split('/').pop()}?key=${apiKey}`;
      try {
        const resp = UrlFetchApp.fetch(checkUrl);
        const data = JSON.parse(resp.getContentText());
        state = data.state;
        if (state === "FAILED") throw new Error("Gemini File Processing Failed");
      } catch(e) {
        console.warn("  -> Status check warning: " + e.message);
      }
      attempts++;
    }
    
    // 4. 生成リクエスト
    const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_CONFIG.MODEL_ID}:generateContent?key=${apiKey}`;
    
    const prompt = `
      Analyze this book cover.
      Extract in Japanese: Author, Title, Volume, Category.
      Category must be ONE of: ['Manga', 'Novel', 'Humanities/Business', 'Technical', 'Other'].
      If volume is not clear, null.
      Return strictly JSON: {"author": "", "title": "", "volume": "", "category": ""}.
    `;

    const payload = {
      contents: [{
        parts: [
          { text: prompt },
          { file_data: { mime_type: "application/pdf", file_uri: fileUri } }
        ]
      }],
      generationConfig: {
        temperature: 0.2,
        response_mime_type: "application/json"
      }
    };

    const options = {
      method: 'post',
      headers: { 'Content-Type': 'application/json' },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };
    
    // Retry logic for 429 Errors
    let response;
    let retryDetail = "";
    for (let i = 0; i < 5; i++) {
        response = UrlFetchApp.fetch(endpoint, options);
        if (response.getResponseCode() !== 429) {
            break; // Success or other error
        }
        console.warn(`Gemini 429 Rate Limit hit. Retrying in ${Math.pow(2, i)}s...`);
        Utilities.sleep(Math.pow(2, i) * 1000); // 1, 2, 4, 8, 16 sec
        retryDetail = response.getContentText();
    }
    
    const json = JSON.parse(response.getContentText());
    
    if (json.error) {
      console.error("Gemini Error: " + JSON.stringify(json.error));
      return null;
    }
    
    const content = json.candidates[0].content.parts[0].text;
    const parsed = JSON.parse(content);
    // Gemini sometimes returns an array [ { ... } ]
    return Array.isArray(parsed) ? parsed[0] : parsed;
    
  } catch (e) {
    console.error("AI Analysis Failed: " + e.toString());
    return null;
  }
}

/**
 * BlobをGeminiへアップロードするヘルパー (Resumable Upload)
 */
function uploadBlobToGemini_(blob, apiKey) {
  const size = blob.getBytes().length;
  const mimeType = blob.getContentType();
  const displayName = 'cover_temp.pdf';

  // 1. Start Upload Session
  const initUrl = `https://generativelanguage.googleapis.com/upload/v1beta/files?key=${apiKey}`;
  const initHeaders = {
    'X-Goog-Upload-Protocol': 'resumable',
    'X-Goog-Upload-Command': 'start',
    'X-Goog-Upload-Header-Content-Length': size.toString(),
    'X-Goog-Upload-Header-Content-Type': mimeType,
    'Content-Type': 'application/json'
  };
  const initBody = JSON.stringify({ file: { display_name: displayName } });

  const initResponse = UrlFetchApp.fetch(initUrl, {
    method: 'post',
    headers: initHeaders,
    payload: initBody,
    muteHttpExceptions: true
  });

  if (initResponse.getResponseCode() !== 200) {
    throw new Error(`Failed to initiate upload: ${initResponse.getContentText()}`);
  }

  const uploadUrl = initResponse.getHeaders()['x-goog-upload-url'];
  
  // 2. Upload (Small file, single chunk is fine usually, but Resumable flow requires strict headers)
  // For small files (<8MB), we can upload in one go if we use the uploadUrl.
  // Or just chunk it once.
  
  const uploadHeaders = {
    'X-Goog-Upload-Offset': '0',
    'X-Goog-Upload-Command': 'upload, finalize'
  };

  const uploadOptions = {
    method: 'post',
    headers: uploadHeaders,
    payload: blob,
    muteHttpExceptions: true
  };

  const uploadResponse = UrlFetchApp.fetch(uploadUrl, uploadOptions);
  
  if (uploadResponse.getResponseCode() !== 200) {
    throw new Error(`Upload failed: ${uploadResponse.getContentText()}`);
  }
  
  const fileInfo = JSON.parse(uploadResponse.getContentText());
  return fileInfo.file.uri;
}

function constructFileName(metadata) {
  const sanitize = (str) => str ? str.replace(/[\/\\?%*:|"<>]/g, '-') : '';
  const author = sanitize(metadata.author) || 'UnknownAuthor';
  const title = sanitize(metadata.title) || 'UnknownTitle';
  
  let volume = metadata.volume ? String(metadata.volume) : '';
  // 数字のみの場合は2桁埋めする (1 -> 01)
  if (volume && /^\d+$/.test(volume)) {
    volume = volume.padStart(2, '0');
  }
  volume = sanitize(volume);

  let name = `${author}_${title}`;
  if (volume) name += `_${volume}`;
  return name + '.pdf';
}
