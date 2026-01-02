
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import google.auth
import io
import os

def download_pdf():
    creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/drive.readonly'])
    drive = build('drive', 'v3', credentials=creds)

    file_id = '1CKLj8jztwQTc4Tmr-J_mIr-c5Oq944MS'
    dest_path = '/Users/takagishota/Documents/KnowledgeBase/戦略ごっこ_マーケティング以前の問題.pdf'
    
    print(f"Downloading file ID: {file_id} to {dest_path}")
    
    request = drive.files().get_media(fileId=file_id)

    with open(dest_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f'Progress: {int(status.progress() * 100)}%')
    print('Download complete!')

if __name__ == "__main__":
    download_pdf()
