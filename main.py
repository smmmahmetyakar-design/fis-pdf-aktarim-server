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
import re

# Try to import OCR
try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

# Try to import PDF support
try:
    from pdf2image import convert_from_path
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
        """Process a single receipt file (image or PDF)."""
        try:
            if not HAS_OCR:
                self.skipped.append((filename, "OCR not available - install pytesseract"))
                return

            # Check if it's a PDF
            if filename.lower().endswith('.pdf'):
                if not HAS_PDF:
                    self.skipped.append((filename, "PDF support not available - install pdf2image"))
                    return
                
                # Convert PDF to images
                try:
                    images = convert_from_path(file_path)
                except Exception as e:
                    self.skipped.append((filename, f"Failed to convert PDF: {str(e)[:50]}"))
                    return
                
                # Process each page
                if not images:
                    self.skipped.append((filename, "PDF has no pages"))
                    return
                
                all_text = ""
                for page_num, image in enumerate(images):
                    text = pytesseract.image_to_string(image, lang='tur+eng')
                    if text.strip():
                        all_text += text + "\n"
                
                text = all_text
            else:
                # Regular image file
                image = Image.open(file_path)
                text = pytesseract.image_to_string(image, lang='tur+eng')

            if not text.strip():
                self.skipped.append((filename, "Text extraction failed - too blurry or unreadable"))
                return

            # Parse receipt
            receipt = self._parse_text(text, filename)

            if receipt:
                self.receipts.append(receipt)
            else:
                self.skipped.append((filename, "Could not parse all 9 fields"))

        except Exception as e:
            self.skipped.append((filename, f"Error: {str(e)[:50]}"))

    def _parse_text(self, text: str, source: str) -> Dict | None:
        """
        Parse OCR text into receipt fields using regex patterns.

        Extracts 9 required fields from Turkish receipts:
        - EVRAK TARİHİ (receipt date DD/MM/YYYY)
        - EVRAK NO (receipt number)
        - TCKN/VKN (tax ID)
        - SOYADI ÜNVAN (vendor name/company)
        - ADI DEVAMI (vendor name continuation)
        - TUTAR (amount before tax)
        - KDV ORANI (VAT rate %)
        - KDV TUTARI (VAT amount)
        - TOPLAM TUTAR (total amount)
        """

        receipt = {field: '' for field in CSV_HEADERS}
        field_count = 0

        # Pattern 1: Date in DD/MM/YYYY format (handles both dashes and slashes)
        date_match = re.search(r'\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b', text)
        if date_match:
            day, month, year = date_match.groups()
            # Validate date range
            if 1 <= int(day) <= 31 and 1 <= int(month) <= 12 and 2000 <= int(year) <= 2099:
                receipt['EVRAK TARİHİ'] = f"{day:>02s}/{month:>02s}/{year}"
                field_count += 1

        # Pattern 2: Tax ID (TCKN/VKN) - 10 or 11 digit number
        vkn_match = re.search(r'\b(\d{10,11})\b', text)
        if vkn_match:
            receipt['TCKN/VKN'] = vkn_match.group(1)
            field_count += 1

        # Pattern 3: Receipt number (often alphanumeric after "Belge No", "Evrak No", "No:", etc.)
        no_match = re.search(r'(?:Belge No|Evrak No|No|Fiş No)[:\s]+([A-Za-z0-9\-]{2,20})', text, re.IGNORECASE)
        if no_match:
            receipt['EVRAK NO'] = no_match.group(1).strip()
            field_count += 1
        else:
            # Fallback: look for 4-6 digit number
            no_fallback = re.search(r'(?:^|\s)(\d{3,8})(?:\s|$)', text, re.MULTILINE)
            if no_fallback:
                receipt['EVRAK NO'] = no_fallback.group(1)
                field_count += 1

        # Pattern 4: Vendor name - typically appears early in receipt
        # Look for lines with company/shop names (usually after header/date)
        lines = text.split('\n')
        vendor_found = False
        for i, line in enumerate(lines):
            line_clean = line.strip()
            # Skip very short lines and common noise
            if 3 < len(line_clean) < 100 and not re.match(r'^\d+[.,]?\d*$', line_clean):
                # Check if line looks like vendor name (not just numbers or common receipt headers)
                if not any(header in line_clean.upper() for header in ['TOPLAM', 'TUTAR', 'KDV', 'EVRAK', 'TARİH']):
                    receipt['SOYADI ÜNVAN'] = line_clean[:50]  # First 50 chars
                    # Try to get continuation from next line if it exists
                    if i + 1 < len(lines) and 3 < len(lines[i + 1].strip()) < 50:
                        next_line = lines[i + 1].strip()
                        if not any(c.isdigit() for c in next_line[:5]):  # Doesn't start with numbers
                            receipt['ADI DEVAMI'] = next_line[:50]
                    vendor_found = True
                    field_count += 1
                    break

        # Pattern 5: Amounts - look for currency values
        # Turkish format: number with comma as decimal (1.234,56) or just (1234,56)
        amount_pattern = r'(?:Tutar|Total|Toplam)[:\s]*([0-9.,]+)'
        amount_matches = re.findall(amount_pattern, text, re.IGNORECASE)

        total_pattern = r'(?:Genel Toplam|TOPLAM TUTAR|Total)[:\s]*([0-9.,]+)'
        total_matches = re.findall(total_pattern, text, re.IGNORECASE)

        # VAT pattern - look for KDV percentage and amount
        kdt_rate_pattern = r'(?:KDV|VAT|Vergi)[:\s]*(%?\d+[.,]?\d*\s*%?)'
        vat_rate_matches = re.findall(kdt_rate_pattern, text, re.IGNORECASE)

        # Extract amount (before tax)
        if amount_matches:
            amt = self._normalize_amount(amount_matches[-1])
            if amt:
                receipt['TUTAR'] = amt
                field_count += 1

        # Extract total amount
        if total_matches:
            total = self._normalize_amount(total_matches[-1])
            if total:
                receipt['TOPLAM TUTAR'] = total
                field_count += 1
        elif amount_matches:
            # If no explicit total, use last found amount
            receipt['TOPLAM TUTAR'] = receipt['TUTAR']

        # Extract VAT rate
        if vat_rate_matches:
            vat_str = vat_rate_matches[-1].strip()
            # Clean up the VAT rate string
            vat_rate = re.sub(r'[^\d.,]', '', vat_str)
            if vat_rate:
                # Ensure it looks like a percentage
                if '.' not in vat_rate or vat_rate.count('.') == 1:
                    receipt['KDV ORANI'] = f"%{vat_rate}" if '%' not in vat_str else vat_str
                    field_count += 1

        # Calculate VAT amount if we have rate and amount
        if receipt.get('TUTAR') and receipt.get('KDV ORANI'):
            try:
                amount_val = float(receipt['TUTAR'].replace('.', '').replace(',', '.'))
                rate_str = receipt['KDV ORANI'].replace('%', '').replace(',', '.')
                rate_val = float(rate_str) / 100
                vat_amount = amount_val * rate_val
                receipt['KDV TUTARI'] = f"{vat_amount:.2f}".replace('.', ',')
                field_count += 1
            except (ValueError, ZeroDivisionError):
                pass

        # Consider a receipt valid if we extracted at least 6 of 9 fields
        # (some fields like continuation may be optional)
        required_minimum = 6
        if field_count >= required_minimum:
            return receipt

        return None

    def _normalize_amount(self, amount_str: str) -> str:
        """Convert Turkish-format amount to standardized format."""
        amount_str = amount_str.strip()
        # Remove spaces used as thousand separator
        amount_str = amount_str.replace(' ', '')
        # Turkish uses comma as decimal separator, dot as thousand separator
        # Convert to English format first for validation
        if ',' in amount_str and '.' in amount_str:
            # Determine which is decimal based on position
            if amount_str.rindex(',') > amount_str.rindex('.'):
                # Comma is after dot, so dot is thousand separator
                amount_str = amount_str.replace('.', '').replace(',', '.')
            else:
                # Keep as is
                pass
        elif ',' in amount_str:
            # Only comma - it's the decimal separator
            amount_str = amount_str.replace(',', '.')
        # Validate it's a number
        try:
            float(amount_str)
            return amount_str
        except ValueError:
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
