# Fiş PDF Aktarım Aracı

Turkish business receipt (fiş/fatura) image to accounting CSV converter.

**URL:** `http://100.74.86.128:8093`  
**Port:** `8093`  
**Container:** `fis-pdf-aktarim`

## Features

- 📤 Upload receipt images (JPEG, PNG) or PDFs
- 🔍 Extract data using OCR (Turkish + English)
- 📊 Generate semicolon-delimited CSV with UTF-8 BOM
- 💾 Download ready-to-import accounting CSV
- 📋 Report extracted vs. skipped receipts

## Output Format

9-field CSV (semicolon-delimited, UTF-8 BOM):

```
EVRAK TARİHİ;EVRAK NO;TCKN/VKN;SOYADI ÜNVAN;ADI DEVAMI;TUTAR;KDV ORANI;KDV TUTARI;TOPLAM TUTAR
15/08/2026;0055;11111111111;AKYOL OTOMOTİV;SAN. VE TİC. A.Ş.;2350.00;%18;412.50;2762.50
```

## Deployment

### 1. Clone Repository

```bash
cd /home/muhasebe/firmalar
git clone https://github.com/smmmahmetyakar-design/fis-pdf-aktarim-server.git
cd fis-pdf-aktarim-server
```

### 2. Build and Run

```bash
# First time setup
docker build -t fis-pdf-aktarim-server:latest .
docker run -d \
    --name fis-pdf-aktarim \
    --restart unless-stopped \
    -p 8093:8093 \
    -v /tmp/fis-uploads:/tmp/fis-uploads \
    -v /tmp/fis-outputs:/tmp/fis-outputs \
    fis-pdf-aktarim-server:latest
```

### 3. Update (via SSH)

```bash
ssh ahmet@dellserver
cd /home/muhasebe/firmalar/fis-pdf-aktarim-server
bash guncelle.sh
```

## Testing

Check service health:
```bash
curl http://100.74.86.128:8093/health
```

Expected response:
```json
{
  "status": "ok",
  "service": "Fiş PDF Aktarım Aracı",
  "ocr_available": true,
  "pdf_support": true
}
```

## API Endpoints

### Upload & Process

**POST** `/api/process`

- Accepts: `multipart/form-data` with file uploads
- Returns: JSON with CSV download URL and summary

**Request:**
```bash
curl -F "files=@receipt1.jpg" \
     -F "files=@receipt2.jpg" \
     http://100.74.86.128:8093/api/process
```

**Response:**
```json
{
  "success": true,
  "summary": {
    "extracted": 2,
    "skipped": 0,
    "skipped_details": []
  },
  "csv_filename": "fis_aktarim_20260922_143015.csv",
  "csv_url": "/download/fis_aktarim_20260922_143015.csv"
}
```

### Download CSV

**GET** `/download/{filename}`

Returns the generated CSV file with proper encoding and delimiter.

### Health Check

**GET** `/health`

Returns service status and feature availability.

## Troubleshooting

### OCR Not Working
- Ensure `tesseract-ocr` and `tesseract-ocr-tur` are installed in Docker
- Check container logs: `docker logs fis-pdf-aktarim`

### File Encoding Issues
- Output always uses UTF-8 with BOM (utf-8-sig) for Turkish software compatibility
- CSV delimiter is semicolon (;) per Turkish locale standard

### Permission Errors
- Ensure `/tmp/fis-uploads` and `/tmp/fis-outputs` directories exist and are writable

```bash
sudo mkdir -p /tmp/fis-uploads /tmp/fis-outputs
sudo chmod 777 /tmp/fis-uploads /tmp/fis-outputs
```

## Integration

### With Other Tools

This tool can be called from:
- Web browser: http://100.74.86.128:8093
- API requests: `/api/process` endpoint
- Scripts: Use curl/Python requests to upload files

### Data Flow

```
Receipt Images
       ↓
   [Upload]
       ↓
   [OCR Extract]
       ↓
   [Parse Fields]
       ↓
   [Validate]
       ↓
   [CSV Export]
       ↓
   [Download/Import]
```

## Directory Structure

```
fis-pdf-aktarim-server/
├── main.py              # FastAPI application
├── Dockerfile          # Docker configuration
├── requirements.txt    # Python dependencies
├── guncelle.sh        # Update script
├── README.md          # This file
├── .gitignore         # Git ignore rules
└── LICENSE
```

## License

Internal use only.
