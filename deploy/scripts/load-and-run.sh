#!/bin/bash

# Segments Manager - Load and Run Container Image
# This script loads the container image and runs it in air-gapped environment

set -e

PROJECT_NAME="segments-manager"
IMAGE_NAME="segments-manager"
IMAGE_TAG="${1:-latest}"
CONTAINER_NAME="segments-manager"
SCRIPT_DIR="$(dirname "$0")"

echo "🚀 Segments Manager - Load and Run Container Image"
echo "==============================================="

# Check if podman is available
if ! command -v podman &> /dev/null; then
    echo "❌ Podman is not installed. Please install podman first."
    exit 1
fi

# Check if image file exists
IMAGE_FILE="${IMAGE_NAME}-${IMAGE_TAG}.tar"
if [ ! -f "$IMAGE_FILE" ]; then
    echo "❌ Image file not found: $IMAGE_FILE"
    echo "   Please ensure you have transferred the image file to this directory"
    exit 1
fi

echo "📋 Configuration:"
echo "   Image File: $IMAGE_FILE"
echo "   Container: $CONTAINER_NAME"

# Load environment variables if .env exists
if [ -f .env ]; then
    echo "   Environment: .env file found"
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "⚠️  No .env file found. Using default environment variables."
    echo "   Create .env from .env.example for production use"
    
    # Set defaults (WARNING: MONGODB_URL must point at a reachable MongoDB)
    export MONGODB_URL="${MONGODB_URL:-mongodb://localhost:27017}"
    export MONGODB_DB_NAME="${MONGODB_DB_NAME:-segments_manager}"
    # Assigned in a plain if rather than ${VAR:-default}: the JSON's nested
    # braces confuse that expansion and it silently truncates to the first site.
    if [ -z "$SITE_NETWORKS" ]; then
        SITE_NETWORKS='{"site1": {"pool": "192.10.0.0/16", "bmc": "10.50.0.0/16"}, "site2": {"pool": "193.51.0.0/16", "bmc": "10.51.0.0/16"}, "site3": {"pool": "194.52.0.0/16", "bmc": "10.52.0.0/16"}}'
    fi
    export SITE_NETWORKS
    export SERVER_PORT="${SERVER_PORT:-8000}"
fi

echo ""
echo "🔧 Environment Configuration:"
echo "   MongoDB DB: $MONGODB_DB_NAME"
echo "   Site Networks: $SITE_NETWORKS"
# Mask credentials in the connection string before printing
echo "   MongoDB URL: $(echo "$MONGODB_URL" | sed -E 's#://[^@]*@#://****:****@#')"

echo ""
echo "📥 Loading container image..."
podman load -i "$IMAGE_FILE"

if [ $? -eq 0 ]; then
    echo "✅ Container image loaded successfully!"
else
    echo "❌ Failed to load container image"
    exit 1
fi

# Stop existing container if running
echo ""
echo "🛑 Stopping existing container (if running)..."
podman stop $CONTAINER_NAME 2>/dev/null || true
podman rm $CONTAINER_NAME 2>/dev/null || true

echo ""
echo "🚀 Starting Segments Manager container..."
podman run -d \
    --name $CONTAINER_NAME \
    --restart unless-stopped \
    -p 8000:8000 \
    -e MONGODB_URL="$MONGODB_URL" \
    -e MONGODB_DB_NAME="$MONGODB_DB_NAME" \
    -e SITE_NETWORKS="$SITE_NETWORKS" \
    -e SERVER_PORT="$SERVER_PORT" \
    -v ./data:/app/data:Z \
    $IMAGE_NAME:$IMAGE_TAG

if [ $? -eq 0 ]; then
    echo "✅ Container started successfully!"
    
    echo ""
    echo "⏳ Waiting for service to start..."
    sleep 15
    
    # Health check
    echo "🏥 Checking service health..."
    if curl -f http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "✅ Segments Manager is healthy and running!"
        
        echo ""
        echo "🌐 Service Information:"
        echo "   Web UI:  http://localhost:8000"
        echo "   API:     http://localhost:8000/api"
        echo "   Health:  http://localhost:8000/api/health"
        echo "   Logs:    http://localhost:8000/api/logs"
        
        echo ""
        echo "📊 Container Status:"
        podman ps --filter name=$CONTAINER_NAME
        
    else
        echo "❌ Service health check failed"
        echo ""
        echo "📋 Container logs (last 20 lines):"
        podman logs --tail 20 $CONTAINER_NAME
        
        echo ""
        echo "🔍 Troubleshooting:"
        echo "   1. Check MongoDB connectivity (MONGODB_URL reachable from the container)"
        echo "   2. Verify MongoDB credentials in MONGODB_URL are valid"
        echo "   3. Verify all environment variables are set (especially SITE_NETWORKS)"
        echo "   4. Check container logs: podman logs $CONTAINER_NAME"
    fi
    
else
    echo "❌ Failed to start container"
    exit 1
fi

echo ""
echo "🎉 Deployment completed!"
echo ""
echo "📋 Useful Commands:"
echo "   View logs:    podman logs $CONTAINER_NAME"
echo "   Stop:         podman stop $CONTAINER_NAME"
echo "   Restart:      podman restart $CONTAINER_NAME"
echo "   Remove:       podman rm $CONTAINER_NAME"