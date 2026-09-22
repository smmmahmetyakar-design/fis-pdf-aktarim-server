FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for OCR and image processing
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-tur poppler-utils \
    libtesseract-dev \
    libpoppler-cpp-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY main.py .

# Create temp directories
RUN mkdir -p /tmp/fis-uploads /tmp/fis-outputs

# Expose port
EXPOSE 8093

# Run the application
CMD ["python", "main.py"]
