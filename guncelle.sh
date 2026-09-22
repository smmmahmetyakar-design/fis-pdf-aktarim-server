#!/bin/bash

# Fiş PDF Aktarım Aracı - Update Script
# Usage: bash guncelle.sh
# Pulls latest from GitHub, rebuilds Docker image, and restarts container

set -e

REPO_NAME="fis-pdf-aktarim-server"
CONTAINER_NAME="fis-pdf-aktarim"
IMAGE_NAME="fis-pdf-aktarim-server"
PORT="8093"

echo "🔄 Fiş PDF Aktarım Aracı Güncelleniyor..."
echo "---"

# Pull latest from GitHub
echo "📦 GitHub'dan çekiliyor..."
git pull origin main

# Build Docker image
echo "🏗️  Docker image oluşturuluyor..."
docker build -t $IMAGE_NAME:latest .

# Stop and remove old container
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "🛑 Eski container kapatılıyor..."
    docker stop $CONTAINER_NAME 2>/dev/null || true
    docker rm $CONTAINER_NAME 2>/dev/null || true
fi

# Run new container
echo "🚀 Yeni container başlatılıyor..."
docker run -d \
    --name $CONTAINER_NAME \
    --restart unless-stopped \
    -p $PORT:8093 \
    -v /tmp/fis-uploads:/tmp/fis-uploads \
    -v /tmp/fis-outputs:/tmp/fis-outputs \
    $IMAGE_NAME:latest

echo "---"
echo "✅ Güncelleme tamamlandı!"
echo "📍 URL: http://100.74.86.128:$PORT"
echo "🏥 Health check: http://100.74.86.128:$PORT/health"
