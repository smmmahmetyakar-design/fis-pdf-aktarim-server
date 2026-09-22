#!/usr/bin/env python3
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Fiş PDF Aktarım Aracı", version="1.0.0")

@app.get("/health")
async def health():
    return {
        'status': 'ok',
        'service': 'Fiş PDF Aktarım Aracı',
        'ocr_available': True,
        'pdf_support': True
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8093)
