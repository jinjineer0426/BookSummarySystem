#!/usr/bin/env python3
"""
PDF処理スクリプト: 
1. 本紙PDFから1枚目を削除
2. 表紙PDFを左90度回転して本紙の先頭に挿入
"""

import io
import os
from google.cloud import storage
from google.oauth2 import service_account
import googleapiclient.discovery
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from pypdf import PdfReader, PdfWriter

# Google Drive File IDs
MAIN_PDF_ID = "16bnbQgys-mq29_4-ae_b37qS0qIKCPLE"  # 本紙（1枚目削除対象）
COVER_PDF_ID = "1HSyavvq4xJdMNxCqYoJwXdTArECxYH_r"  # 表紙（左90度回転）

def get_drive_service():
    """Create Google Drive API service"""
    from google.auth import default
    credentials, _ = default(scopes=['https://www.googleapis.com/auth/drive'])
    return googleapiclient.discovery.build('drive', 'v3', credentials=credentials)

def download_pdf(service, file_id):
    """Download PDF from Google Drive"""
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
        print(f"  Download progress: {int(status.progress() * 100)}%")
    
    buffer.seek(0)
    return buffer

def process_pdfs():
    """Main PDF processing function"""
    print("=== PDF処理開始 ===")
    
    # Drive API初期化
    service = get_drive_service()
    
    # 1. PDFダウンロード
    print("\n1. 本紙PDFをダウンロード中...")
    main_pdf_buffer = download_pdf(service, MAIN_PDF_ID)
    main_reader = PdfReader(main_pdf_buffer)
    print(f"   本紙: {len(main_reader.pages)}ページ")
    
    print("\n2. 表紙PDFをダウンロード中...")
    cover_pdf_buffer = download_pdf(service, COVER_PDF_ID)
    cover_reader = PdfReader(cover_pdf_buffer)
    print(f"   表紙: {len(cover_reader.pages)}ページ")
    
    # 2. 新しいPDFを作成
    print("\n3. PDFを結合中...")
    writer = PdfWriter()
    
    # 表紙を左90度（反時計回り = -90度 = 270度）回転して追加
    for page in cover_reader.pages:
        page.rotate(-90)  # 左90度回転
        writer.add_page(page)
    print(f"   表紙 {len(cover_reader.pages)}ページを左90度回転して追加")
    
    # 本紙から1枚目を除いて追加
    for i, page in enumerate(main_reader.pages):
        if i == 0:
            print(f"   本紙1枚目をスキップ")
            continue
        writer.add_page(page)
    print(f"   本紙 {len(main_reader.pages) - 1}ページを追加")
    
    # 3. 結果を保存
    output_buffer = io.BytesIO()
    writer.write(output_buffer)
    output_buffer.seek(0)
    
    total_pages = len(cover_reader.pages) + len(main_reader.pages) - 1
    print(f"\n4. 完成: 合計 {total_pages}ページ")
    
    # 4. ローカルに保存（先に実行）
    local_path = os.path.expanduser("~/Desktop/失敗の本質_結合済み.pdf")
    with open(local_path, 'wb') as f:
        f.write(output_buffer.read())
    print(f"\n5. ローカル保存完了: {local_path}")
    
    # 5. Google Driveにアップロード（オプション）
    print("\n6. Google Driveにアップロード中...")
    try:
        output_buffer.seek(0)
        media = MediaIoBaseUpload(output_buffer, mimetype='application/pdf', resumable=True)
        updated_file = service.files().update(
            fileId=MAIN_PDF_ID,
            media_body=media
        ).execute()
        print(f"   完了: https://drive.google.com/file/d/{MAIN_PDF_ID}/view")
    except Exception as e:
        print(f"   アップロード失敗: {e}")
        print(f"   手動でアップロードしてください: {local_path}")

    
    print("\n=== 処理完了 ===")

if __name__ == "__main__":
    process_pdfs()
