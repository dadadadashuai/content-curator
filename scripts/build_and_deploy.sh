#!/bin/bash
# content-curator/scripts/build_and_deploy.sh
set -e

PROJECT_DIR="/home/ds/ai-suite/content-curator"
IMAGE_NAME="content-curator"
CONTAINER_NAME="content-curator"

echo "=== 1. Read SiliconFlow API key from Hermes config ==="
SF_KEY=$(python3 -c "
with open('/home/ds/.hermes/config.yaml') as f:
    for line in f:
        if 'api_key' in line and 'sk-' in line:
            print(line.strip().split('api_key:')[1].strip()); break
")
if [ -z "$SF_KEY" ]; then echo "ERROR: SF_API_KEY not found"; exit 1; fi
echo "API key found."

echo "=== 2. Build Docker image ==="
cd "$PROJECT_DIR"
docker build -t ${IMAGE_NAME}:latest .

echo "=== 3. Stop old container ==="
docker stop ${CONTAINER_NAME} 2>/dev/null || true
docker rm ${CONTAINER_NAME} 2>/dev/null || true

echo "=== 4. Start new container ==="
docker run -d \
  --name ${CONTAINER_NAME} \
  --network host \
  --restart unless-stopped \
  -v /home/ds/ai-suite/syncthing/data/Vault:/app/vault \
  -v ${PROJECT_DIR}/cookies.txt:/app/cookies.txt \
  -v ${PROJECT_DIR}/data:/app/data \
  -v ${PROJECT_DIR}/cache:/app/cache \
  -e VAULT_PATH=/app/vault \
  -e SF_API_KEY="$SF_KEY" \
  -e COOKIES_FILE=/app/cookies.txt \
  -e CACHE_DIR=/app/cache \
  ${IMAGE_NAME}:latest

echo "=== 5. Wait and health check ==="
sleep 3
curl -s http://localhost:9100/api/health && echo "" || echo "Health check FAILED"

echo "=== Done ==="
