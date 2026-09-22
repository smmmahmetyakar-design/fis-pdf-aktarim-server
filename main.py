#!/usr/bin/env python3
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
import os, csv, tempfile, re
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime

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

UPLOAD_DIR = Path("/tmp/fis-uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = Path("/tmp/fis-outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf', '.JPG', '.JPEG', '.PNG', '.PDF'}

CSV_HEADERS = ['EVRAK TARİHİ', 'EVRAK NO', 'TCKN/VKN', 'SOYADI ÜNVAN', 'ADI DEVAMI', 'TUTAR', 'KDV ORANI', 'KDV TUTARI', 'TOPLAM TUTAR']

class ReceiptProcessor:
    def __init__(self):
        self.receipts: List[Dict] = []
        self.skipped: List[Tuple[str, str]] = []

    def process_file(self, file_path: str, filename: str) -> None:
        try:
            if not HAS_OCR:
                self.skipped.append((filename, "OCR not available"))
                return
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image, lang='tur+eng')
            if not text.strip():
                self.skipped.append((filename, "Text extraction failed"))
                return
            receipt = self._parse_text(text, filename)
            if receipt:
                self.receipts.append(receipt)
            else:
                self.skipped.append((filename, "Could not parse all 9 fields"))
        except Exception as e:
            self.skipped.append((filename, f"Error: {str(e)[:50]}"))

    def _parse_text(self, text: str, source: str) -> Dict | None:
        receipt = {field: '' for field in CSV_HEADERS}
        field_count = 0
        
        # Date: 25-08-2026 or 25/08/2026 format
        date_match = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', text)
        if date_match:
            day, month, year = date_match.groups()
            if 1 <= int(day) <= 31 and 1 <= int(month) <= 12:
                receipt['EVRAK TARİHİ'] = f"{int(day):02d}/{int(month):02d}/{year}"
                field_count += 1
        
        # Tax ID: 10-11 digits (VD: 0450017361 or similar)
        vkn_match = re.search(r'(?:VD|Vergi Dairesi|TCKN|VKN)[\s:]*(\d{10,11})', text, re.IGNORECASE)
        if vkn_match:
            receipt['TCKN/VKN'] = vkn_match.group(1)
            field_count += 1
        else:
            # Fallback: any 10-11 digit number
            vkn_fallback = re.search(r'\b(\d{10,11})\b', text)
            if vkn_fallback:
                receipt['TCKN/VKN'] = vkn_fallback.group(1)
                field_count += 1
        
        # Receipt number: FİŞ NO: 101
        no_match = re.search(r'FİŞ\s+NO\s*[:]*\s*(\d+)', text, re.IGNORECASE)
        if no_match:
            receipt['EVRAK NO'] = no_match.group(1)
            field_count += 1
        
        # Company name: First non-header line
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if 3 < len(line) < 100 and not re.match(r'^\d+', line):
                if not any(x in line.upper() for x in ['TOPLAM', 'TUTAR', 'KDV', 'TARİH', 'SAAt']):
                    receipt['SOYADI ÜNVAN'] = line[:50]
                    field_count += 1
                    break
        
        # Amounts: *4.720,00 format (Turkish: . = thousand, , = decimal)
        # TUTAR line
        tutar_match = re.search(r'VEDER.*?[*]?([\d.]+,\d{2})', text, re.IGNORECASE)
        if tutar_match:
            amt_str = tutar_match.group(1)
            receipt['TUTAR'] = amt_str
            field_count += 1
        
        # KDV amount: KDV *786,67
        kdv_match = re.search(r'KDV\s*[*]?([\d.]+,\d{2})', text, re.IGNORECASE)
        if kdv_match:
            receipt['KDV TUTARI'] = kdv_match.group(1)
            field_count += 1
            
            # Calculate KDV rate if we have TUTAR
            if receipt.get('TUTAR'):
                try:
                    tutar = float(receipt['TUTAR'].replace('.', '').replace(',', '.'))
                    kdv_amt = float(kdv_match.group(1).replace('.', '').replace(',', '.'))
                    if tutar > 0:
                        rate = (kdv_amt / tutar) * 100
                        receipt['KDV ORANI'] = f"%{rate:.0f}"
                        field_count += 1
                except:
                    pass
        
        # Total: TOP *4.720,00
        top_match = re.search(r'TOP\s*[*]?([\d.]+,\d{2})', text, re.IGNORECASE)
        if top_match:
            receipt['TOPLAM TUTAR'] = top_match.group(1)
            field_count += 1
        elif receipt.get('TUTAR'):
            receipt['TOPLAM TUTAR'] = receipt['TUTAR']
        
        return receipt if field_count >= 6 else None

    def export_csv(self, output_path: str) -> None:
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, delimiter=';', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(self.receipts)

    def get_summary(self) -> Dict:
        return {
            'extracted': len(self.receipts),
            'skipped': len(self.skipped),
            'skipped_details': [{'file': f, 'reason': r} for f, r in self.skipped]
        }

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_TEMPLATE

@app.post("/api/process")
async def process_receipts(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    for file in files:
        if Path(file.filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"File type not allowed: {file.filename}")
    processor = ReceiptProcessor()
    with tempfile.TemporaryDirectory() as tmpdir:
        for file in files:
            file_path = Path(tmpdir) / file.filename
            with open(file_path, 'wb') as f:
                content = await file.read()
                f.write(content)
            processor.process_file(str(file_path), file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"fis_aktarim_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename
        processor.export_csv(str(output_path))
        return {"success": True, "summary": processor.get_summary(), "csv_filename": output_filename, "csv_url": f"/download/{output_filename}"}

@app.get("/download/{filename}")
async def download_csv(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=filename, media_type="text/csv; charset=utf-8")

@app.get("/health")
async def health():
    return {'status': 'ok', 'service': 'Fiş PDF Aktarım Aracı', 'ocr_available': HAS_OCR, 'pdf_support': HAS_PDF}

HTML_TEMPLATE = """<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Fiş PDF Aktarım Aracı</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}.container{background:white;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,0.3);max-width:600px;width:100%;padding:40px}header{text-align:center;margin-bottom:30px}h1{color:#333;font-size:28px;margin-bottom:8px}.subtitle{color:#666;font-size:14px}.upload-area{border:2px dashed #667eea;border-radius:8px;padding:40px 20px;text-align:center;cursor:pointer;transition:all 0.3s;background:#f8f9ff;margin-bottom:20px}.upload-area:hover{border-color:#764ba2;background:#f0f1ff}.upload-area.dragover{border-color:#764ba2;background:#f0f1ff;transform:scale(1.02)}.upload-icon{font-size:48px;margin-bottom:16px}.upload-text{color:#333;font-weight:500;margin-bottom:4px}.upload-hint{color:#999;font-size:12px}input[type="file"]{display:none}.btn{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border:none;padding:12px 30px;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;transition:transform 0.2s,box-shadow 0.2s;width:100%;margin-top:20px}.btn:hover{transform:translateY(-2px);box-shadow:0 10px 20px rgba(102,126,234,0.3)}.btn:active{transform:translateY(0)}.btn:disabled{opacity:0.6;cursor:not-allowed}.spinner{border:4px solid #f3f3f3;border-top:4px solid #667eea;border-radius:50%;width:40px;height:40px;animation:spin 1s linear infinite;margin:20px auto}@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}.results{margin-top:30px;display:none}.results.show{display:block}.result-item{padding:15px;margin-bottom:10px;border-radius:8px;font-size:14px}.result-success{background:#d4edda;color:#155724;border:1px solid #c3e6cb}.result-warning{background:#fff3cd;color:#856404;border:1px solid #ffeaa7}.download-btn{background:#28a745;margin-top:15px}.download-btn:hover{background:#218838;box-shadow:0 10px 20px rgba(40,167,69,0.3)}.stats{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-bottom:20px}.stat{background:#f8f9fa;padding:15px;border-radius:8px;text-align:center}.stat-value{font-size:28px;font-weight:bold;color:#667eea}.stat-label{font-size:12px;color:#666;margin-top:5px}</style></head><body><div class="container"><header><h1>📄 Fiş PDF Aktarım Aracı</h1><p class="subtitle">Receipt images to accounting CSV converter</p></header><div class="upload-area" id="uploadArea"><div class="upload-icon">📁</div><div class="upload-text">Click to select or drag files here</div><div class="upload-hint">Supported: JPEG, PNG, PDF</div><input type="file" id="fileInput" multiple accept=".jpg,.jpeg,.png,.pdf"></div><button class="btn" id="processBtn" disabled>Process Receipts</button><div class="results" id="results"><div class="stats"><div class="stat"><div class="stat-value" id="extractedCount">0</div><div class="stat-label">Extracted</div></div><div class="stat"><div class="stat-value" id="skippedCount">0</div><div class="stat-label">Skipped</div></div></div><div id="skippedDetails"></div><button class="btn download-btn" id="downloadBtn" style="display:none">📥 Download CSV</button></div><div id="spinner" class="spinner" style="display:none"></div></div><script>const uploadArea=document.getElementById('uploadArea');const fileInput=document.getElementById('fileInput');const processBtn=document.getElementById('processBtn');const results=document.getElementById('results');const spinner=document.getElementById('spinner');const downloadBtn=document.getElementById('downloadBtn');let selectedFiles=[];uploadArea.addEventListener('click',()=>fileInput.click());fileInput.addEventListener('change',(e)=>{selectedFiles=Array.from(e.target.files);updateUploadArea()});uploadArea.addEventListener('dragover',(e)=>{e.preventDefault();uploadArea.classList.add('dragover')});uploadArea.addEventListener('dragleave',()=>{uploadArea.classList.remove('dragover')});uploadArea.addEventListener('drop',(e)=>{e.preventDefault();uploadArea.classList.remove('dragover');selectedFiles=Array.from(e.dataTransfer.files);updateUploadArea()});function updateUploadArea(){if(selectedFiles.length>0){uploadArea.innerHTML=`<div class="upload-icon">✓</div><div class="upload-text">${selectedFiles.length} file(s) selected</div>`;processBtn.disabled=false}}processBtn.addEventListener('click',async()=>{if(selectedFiles.length===0)return;const formData=new FormData();selectedFiles.forEach(file=>formData.append('files',file));spinner.style.display='block';processBtn.disabled=true;results.classList.remove('show');try{const response=await fetch('/api/process',{method:'POST',body:formData});const data=await response.json();displayResults(data)}catch(error){alert('Error: '+error.message)}finally{spinner.style.display='none';processBtn.disabled=false}});function displayResults(data){const summary=data.summary;document.getElementById('extractedCount').textContent=summary.extracted;document.getElementById('skippedCount').textContent=summary.skipped;const skippedDetails=document.getElementById('skippedDetails');skippedDetails.innerHTML='';if(summary.skipped_details&&summary.skipped_details.length>0){const title=document.createElement('div');title.style.marginBottom='10px';title.style.fontWeight='600';title.textContent='Skipped Files:';skippedDetails.appendChild(title);summary.skipped_details.forEach(item=>{const div=document.createElement('div');div.className='result-item result-warning';div.innerHTML=`<strong>${item.file}</strong><br/>${item.reason}`;skippedDetails.appendChild(div)})}if(summary.extracted>0){downloadBtn.style.display='block';downloadBtn.onclick=()=>{window.location.href=data.csv_url}}results.classList.add('show')};</script></body></html>"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8093)
