#!/usr/bin/env python3
"""
Fiş PDF Aktarım Aracı (Receipt PDF Transfer Tool)
FastAPI web application for converting receipt images/PDFs to accounting CSV

Port: 8093
URL: http://dellserver:8093 or http://100.74.86.128:8093
"""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os
import csv
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple
import shutil
from datetime import datetime

# Try to import OCR
try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

app = FastAPI(title="Fiş PDF Aktarım Aracı", version="1.0.0")

# Configuration
UPLOAD_DIR = Path("/tmp/fis-uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = Path("/tmp/fis-outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# Allowed file types
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf', '.JPG', '.JPEG', '.PNG', '.PDF'}

# CSV field headers
CSV_HEADERS = [
    'EVRAK TARİHİ',
    'EVRAK NO',
    'TCKN/VKN',
    'SOYADI ÜNVAN',
    'ADI DEVAMI',
    'TUTAR',
    'KDV ORANI',
    'KDV TUTARI',
    'TOPLAM TUTAR'
]


class ReceiptProcessor:
    """Process receipt images and extract data."""

    def __init__(self):
        self.receipts: List[Dict] = []
        self.skipped: List[Tuple[str, str]] = []

    def process_file(self, file_path: str, filename: str) -> None:
        """Process a single receipt file."""
        try:
            if not HAS_OCR:
                self.skipped.append((filename, "OCR not available - install pytesseract"))
                return

            # Load image
            image = Image.open(file_path)

            # Extract text via OCR
            text = pytesseract.image_to_string(image, lang='tur+eng')

            if not text.strip():
                self.skipped.append((filename, "Text extraction failed - too blurry or unreadable"))
                return

            # Parse receipt (placeholder - real parsing would be more sophisticated)
            receipt = self._parse_text(text, filename)

            if receipt:
                self.receipts.append(receipt)
            else:
                self.skipped.append((filename, "Could not parse all 9 fields"))

        except Exception as e:
            self.skipped.append((filename, f"Error: {str(e)[:50]}"))

    def _parse_text(self, text: str, source: str) -> Dict | None:
        """
        Parse OCR text into receipt fields.

        This is a template - in production, this would:
        - Use regex patterns for Turkish date formats
        - Extract amounts from various positions
        - Identify vendor names and tax IDs
        - Handle common receipt layouts
        """
        # For now, return None to add to skipped
        # User can manually enter or we can enhance OCR parsing
        return None

    def add_manual_receipt(self, data: Dict[str, str]) -> bool:
        """Add manually-entered receipt."""
        receipt = {field: data.get(field, '') for field in CSV_HEADERS}

        if not receipt.get('EVRAK TARİHİ'):
            return False

        self.receipts.append(receipt)
        return True

    def export_csv(self, output_path: str) -> None:
        """Export receipts to CSV with UTF-8 BOM and semicolon delimiter."""
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=CSV_HEADERS,
                delimiter=';',
                quoting=csv.QUOTE_MINIMAL
            )
            writer.writeheader()
            writer.writerows(self.receipts)

    def get_summary(self) -> Dict:
        """Get processing summary."""
        return {
            'extracted': len(self.receipts),
            'skipped': len(self.skipped),
            'skipped_details': [{'file': f, 'reason': r} for f, r in self.skipped]
        }


# Routes

@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main web interface."""
    return HTML_TEMPLATE


@app.post("/api/process")
async def process_receipts(files: List[UploadFile] = File(...)):
    """Process uploaded receipt files and return CSV."""

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    # Validate file types
    for file in files:
        if Path(file.filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed: {file.filename}. Allowed: JPEG, PNG, PDF"
            )

    processor = ReceiptProcessor()

    # Save uploaded files and process
    with tempfile.TemporaryDirectory() as tmpdir:
        for file in files:
            file_path = Path(tmpdir) / file.filename

            # Save uploaded file
            with open(file_path, 'wb') as f:
                content = await file.read()
                f.write(content)

            # Process file
            processor.process_file(str(file_path), file.filename)

        # Generate output CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"fis_aktarim_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        processor.export_csv(str(output_path))

        # Return summary and CSV download link
        return JSONResponse({
            'success': True,
            'summary': processor.get_summary(),
            'csv_filename': output_filename,
            'csv_url': f"/download/{output_filename}"
        })


@app.get("/download/{filename}")
async def download_csv(filename: str):
    """Download generated CSV file."""
    file_path = OUTPUT_DIR / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="text/csv; charset=utf-8"
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        'status': 'ok',
        'service': 'Fiş PDF Aktarım Aracı',
        'ocr_available': HAS_OCR,
        'pdf_support': HAS_PDF
    }


# HTML Template

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fiş PDF Aktarım Aracı</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .container {
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 600px;
            width: 100%;
            padding: 40px;
        }

        header {
            text-align: center;
            margin-bottom: 30px;
        }

        h1 {
            color: #333;
            font-size: 28px;
            margin-bottom: 8px;
        }

        .subtitle {
            color: #666;
            font-size: 14px;
        }

        .upload-area {
            border: 2px dashed #667eea;
            border-radius: 8px;
            padding: 40px 20px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
            background: #f8f9ff;
            margin-bottom: 20px;
        }

        .upload-area:hover {
            border-color: #764ba2;
            background: #f0f1ff;
        }

        .upload-area.dragover {
            border-color: #764ba2;
            background: #f0f1ff;
            transform: scale(1.02);
        }

        .upload-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }

        .upload-text {
            color: #333;
            font-weight: 500;
            margin-bottom: 4px;
        }

        .upload-hint {
            color: #999;
            font-size: 13px;
        }

        #fileInput {
            display: none;
        }

        .file-list {
            margin-bottom: 20px;
        }

        .file-item {
            background: #f5f5f5;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 14px;
        }

        .file-item .filename {
            color: #333;
            flex: 1;
        }

        .file-item .size {
            color: #999;
            font-size: 12px;
        }

        .file-item .remove {
            background: #ff4444;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 4px 12px;
            cursor: pointer;
            font-size: 12px;
        }

        .button-group {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
        }

        button {
            flex: 1;
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
        }

        .btn-process {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }

        .btn-process:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
        }

        .btn-process:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .btn-clear {
            background: #f0f0f0;
            color: #333;
        }

        .btn-clear:hover {
            background: #e0e0e0;
        }

        .results {
            display: none;
            background: #f9f9f9;
            border-radius: 8px;
            padding: 24px;
            border-left: 4px solid #667eea;
        }

        .results.show {
            display: block;
        }

        .results h3 {
            color: #333;
            margin-bottom: 16px;
            font-size: 18px;
        }

        .stats {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 16px;
        }

        .stat {
            background: white;
            padding: 16px;
            border-radius: 6px;
            border: 1px solid #eee;
        }

        .stat-number {
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
        }

        .stat-label {
            font-size: 13px;
            color: #666;
            margin-top: 4px;
        }

        .skipped-list {
            max-height: 200px;
            overflow-y: auto;
            margin-top: 12px;
        }

        .skipped-item {
            font-size: 13px;
            color: #666;
            padding: 8px;
            background: white;
            border-radius: 4px;
            margin-bottom: 4px;
            border-left: 3px solid #ff9800;
        }

        .download-btn {
            background: #4CAF50;
            color: white;
            width: 100%;
            padding: 14px;
            text-decoration: none;
            text-align: center;
            border-radius: 6px;
            display: block;
            margin-top: 16px;
            font-weight: 500;
        }

        .download-btn:hover {
            background: #45a049;
        }

        .error {
            background: #ffebee;
            color: #c62828;
            padding: 16px;
            border-radius: 6px;
            margin-bottom: 20px;
            border-left: 4px solid #c62828;
        }

        .loading {
            display: none;
            text-align: center;
            padding: 20px;
        }

        .loading.show {
            display: block;
        }

        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 16px;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .info-box {
            background: #e3f2fd;
            border-left: 4px solid #2196F3;
            padding: 12px;
            border-radius: 4px;
            font-size: 13px;
            color: #1565c0;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📄 Fiş PDF Aktarım Aracı</h1>
            <p class="subtitle">Fatura/Fiş fotoğraflarını muhasebe CSV'sine dönüştür</p>
        </header>

        <div class="info-box">
            💡 JPEG, PNG veya PDF dosyalarını yükle. 9 alandan muhasebe CSV'si oluşturulur.
        </div>

        <div id="errorMessage" class="error" style="display: none;"></div>

        <div class="upload-area" id="uploadArea">
            <div class="upload-icon">📤</div>
            <div class="upload-text">Fiş fotoğraflarını buraya sürükle veya tıkla</div>
            <div class="upload-hint">JPEG, PNG, PDF — max 50 dosya</div>
            <input type="file" id="fileInput" multiple accept=".jpg,.jpeg,.png,.pdf">
        </div>

        <div class="file-list" id="fileList"></div>

        <div class="button-group">
            <button class="btn-process" id="processBtn" onclick="processFiles()">CSV'ye Çevir</button>
            <button class="btn-clear" onclick="clearFiles()">Temizle</button>
        </div>

        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Fişler işleniyor...</p>
        </div>

        <div class="results" id="results">
            <h3>✓ İşlem Tamamlandı</h3>
            <div class="stats">
                <div class="stat">
                    <div class="stat-number" id="extractedCount">0</div>
                    <div class="stat-label">Çıkarılan Fiş</div>
                </div>
                <div class="stat">
                    <div class="stat-number" id="skippedCount">0</div>
                    <div class="stat-label">Atlanmış Fiş</div>
                </div>
            </div>
            <div id="skippedDetails"></div>
            <a id="downloadLink" class="download-btn" href="#">CSV'yi İndir</a>
        </div>
    </div>

    <script>
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');
        const fileList = document.getElementById('fileList');
        const processBtn = document.getElementById('processBtn');
        const loading = document.getElementById('loading');
        const results = document.getElementById('results');
        const errorMessage = document.getElementById('errorMessage');

        let selectedFiles = [];

        // Drag and drop
        uploadArea.addEventListener('click', () => fileInput.click());
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            handleFiles(e.dataTransfer.files);
        });

        fileInput.addEventListener('change', (e) => {
            handleFiles(e.target.files);
        });

        function handleFiles(files) {
            selectedFiles = Array.from(files);
            updateFileList();
            errorMessage.style.display = 'none';
            results.classList.remove('show');
        }

        function updateFileList() {
            fileList.innerHTML = '';
            selectedFiles.forEach((file, index) => {
                const item = document.createElement('div');
                item.className = 'file-item';
                item.innerHTML = `
                    <span class="filename">${file.name}</span>
                    <span class="size">${(file.size / 1024).toFixed(1)} KB</span>
                    <button class="file-item remove" onclick="removeFile(${index})">Sil</button>
                `;
                fileList.appendChild(item);
            });

            processBtn.disabled = selectedFiles.length === 0;
        }

        function removeFile(index) {
            selectedFiles.splice(index, 1);
            updateFileList();
        }

        function clearFiles() {
            selectedFiles = [];
            fileInput.value = '';
            updateFileList();
            results.classList.remove('show');
            errorMessage.style.display = 'none';
        }

        async function processFiles() {
            if (selectedFiles.length === 0) {
                showError('Lütfen dosya seçin');
                return;
            }

            loading.classList.add('show');
            errorMessage.style.display = 'none';

            try {
                const formData = new FormData();
                selectedFiles.forEach(file => {
                    formData.append('files', file);
                });

                const response = await fetch('/api/process', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'İşlem başarısız');
                }

                const data = await response.json();
                showResults(data);

            } catch (error) {
                showError(error.message);
            } finally {
                loading.classList.remove('show');
            }
        }

        function showResults(data) {
            const summary = data.summary;
            document.getElementById('extractedCount').textContent = summary.extracted;
            document.getElementById('skippedCount').textContent = summary.skipped;

            const skippedDetails = document.getElementById('skippedDetails');
            if (summary.skipped_details.length > 0) {
                let html = '<div class="skipped-list"><strong>Atlanmış dosyalar:</strong>';
                summary.skipped_details.forEach(item => {
                    html += `<div class="skipped-item"><strong>${item.file}</strong>: ${item.reason}</div>`;
                });
                html += '</div>';
                skippedDetails.innerHTML = html;
            } else {
                skippedDetails.innerHTML = '';
            }

            const downloadLink = document.getElementById('downloadLink');
            downloadLink.href = data.csv_url;
            downloadLink.download = data.csv_filename;

            results.classList.add('show');
        }

        function showError(message) {
            errorMessage.textContent = '❌ Hata: ' + message;
            errorMessage.style.display = 'block';
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8093)
