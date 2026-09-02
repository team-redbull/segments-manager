#!/bin/bash
################################################################################
# Segments Manager - Deployment Script
################################################################################
# This script builds, deploys, and manages the Segments Manager application
#
# Usage:
#   ./run.sh build          # Build Docker image only
#   ./run.sh start          # Start the application
#   ./run.sh stop           # Stop the application
#   ./run.sh restart        # Restart the application
#   ./run.sh logs           # Show application logs
#   ./run.sh status         # Show container status
#   ./run.sh test           # Run tests
#   ./run.sh clean          # Remove container and volume
#   ./run.sh deploy         # Full deployment (build + start)
################################################################################

set -e  # Exit on error

# Configuration
CONTAINER_NAME="segments-manager"
IMAGE_NAME="segments-manager:latest"
PORT="${SERVER_PORT:-9000}"
ENV_FILE=".env"
VOLUME_NAME="vlan-data"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

################################################################################
# Helper Functions
################################################################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        log_error "Environment file '$ENV_FILE' not found!"
        log_info "Creating from template..."
        cp .env.example .env
        log_warning "Please edit .env with your MONGODB_URL before deploying!"
        exit 1
    fi
}

################################################################################
# Command Functions
################################################################################

build_image() {
    log_info "Building Docker image: $IMAGE_NAME"

    # Get build metadata
    VERSION=$(git describe --tags --always --dirty 2>/dev/null || echo "dev")
    BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

    log_info "Build metadata:"
    log_info "  Version: $VERSION"
    log_info "  Build Date: $BUILD_DATE"
    log_info "  Commit: $COMMIT_SHA"

    podman build \
        --build-arg VERSION="$VERSION" \
        --build-arg BUILD_DATE="$BUILD_DATE" \
        --build-arg COMMIT_SHA="$COMMIT_SHA" \
        -t "$IMAGE_NAME" \
        .

    log_success "Image built successfully!"
}

start_container() {
    check_env_file

    # Load PORT from .env if exists
    if grep -q "^SERVER_PORT=" .env; then
        PORT=$(grep "^SERVER_PORT=" .env | cut -d'=' -f2)
    fi

    log_info "Starting Segments Manager on port $PORT..."

    # Check if container already exists
    if podman ps -a --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        log_warning "Container '$CONTAINER_NAME' already exists"
        log_info "Stopping and removing old container..."
        podman stop "$CONTAINER_NAME" 2>/dev/null || true
        podman rm "$CONTAINER_NAME" 2>/dev/null || true
    fi

    # Create volume if it doesn't exist
    if ! podman volume ls --format "{{.Name}}" | grep -q "^${VOLUME_NAME}$"; then
        log_info "Creating data volume: $VOLUME_NAME"
        podman volume create "$VOLUME_NAME"
    fi

    # Start container
    podman run -d \
        --name "$CONTAINER_NAME" \
        -p "0.0.0.0:${PORT}:${PORT}/tcp" \
        --env-file "$ENV_FILE" \
        -v "${VOLUME_NAME}:/app/data" \
        "$IMAGE_NAME"

    log_success "Container started successfully!"

    # Wait for startup
    log_info "Waiting for application to start..."
    sleep 3

    # Show startup logs
    log_info "Startup logs:"
    podman logs "$CONTAINER_NAME" 2>&1 | tail -15

    echo ""
    log_success "Segments Manager is running!"
    log_info "Access the application at: http://localhost:${PORT}/"
    log_info "View logs with: ./run.sh logs"
}

stop_container() {
    log_info "Stopping Segments Manager..."

    if podman ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        podman stop "$CONTAINER_NAME"
        log_success "Container stopped"
    else
        log_warning "Container is not running"
    fi
}

restart_container() {
    log_info "Restarting Segments Manager..."
    stop_container
    sleep 2
    start_container
}

show_logs() {
    log_info "Showing container logs (press Ctrl+C to exit)..."
    echo ""
    podman logs -f "$CONTAINER_NAME"
}

show_status() {
    log_info "Container Status:"
    echo ""

    if podman ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        podman ps --filter "name=${CONTAINER_NAME}" --format "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}"
        echo ""
        log_success "Container is RUNNING"

        # Show last few log lines
        echo ""
        log_info "Recent logs:"
        podman logs "$CONTAINER_NAME" 2>&1 | tail -10
    else
        log_warning "Container is NOT running"

        # Check if container exists but is stopped
        if podman ps -a --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
            podman ps -a --filter "name=${CONTAINER_NAME}" --format "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"
            echo ""
            log_info "Start with: ./run.sh start"
        else
            log_info "Container does not exist. Deploy with: ./run.sh deploy"
        fi
    fi
}

run_tests() {
    log_info "Running tests..."

    if [ ! -f "test_comprehensive.py" ]; then
        log_error "test_comprehensive.py not found!"
        exit 1
    fi

    # Check if virtual environment exists
    if [ -d ".venv" ]; then
        log_info "Using virtual environment..."
        source .venv/bin/activate
    fi

    # Check if pytest is installed
    if ! command -v pytest &> /dev/null; then
        log_warning "pytest not found. Installing..."
        pip install pytest pytest-asyncio
    fi

    log_info "Running all tests (validation + integration)..."
    pytest test_comprehensive.py -v --tb=short

    log_success "Tests completed!"
}

clean_all() {
    log_warning "This will remove the container and data volume!"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Cleaning up..."

        # Stop and remove container
        if podman ps -a --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
            podman stop "$CONTAINER_NAME" 2>/dev/null || true
            podman rm "$CONTAINER_NAME"
            log_info "Container removed"
        fi

        # Remove volume
        if podman volume ls --format "{{.Name}}" | grep -q "^${VOLUME_NAME}$"; then
            podman volume rm "$VOLUME_NAME"
            log_info "Volume removed"
        fi

        # Optionally remove image
        read -p "Remove Docker image as well? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            podman rmi "$IMAGE_NAME" 2>/dev/null || true
            log_info "Image removed"
        fi

        log_success "Cleanup completed!"
    else
        log_info "Cleanup cancelled"
    fi
}

full_deploy() {
    log_info "Starting full deployment..."
    echo ""

    build_image
    echo ""

    start_container
    echo ""

    log_success "Deployment completed!"
    log_info "Application is available at: http://localhost:${PORT}/"
}

show_help() {
    cat << EOF
Segments Manager - Deployment Script

Usage: ./run.sh [COMMAND]

Commands:
  build          Build Docker image only
  start          Start the application
  stop           Stop the application
  restart        Restart the application
  logs           Show and follow application logs
  status         Show container status and recent logs
  test           Run all tests
  clean          Remove container and volume (prompts for confirmation)
  deploy         Full deployment (build + start)
  help           Show this help message

Examples:
  ./run.sh deploy        # Build and start application
  ./run.sh logs          # View logs
  ./run.sh restart       # Restart after code changes

Environment:
  Configure application settings in .env file
  Default port: 9000 (override with SERVER_PORT in .env)

EOF
}

################################################################################
# Main Script
################################################################################

# Check if podman is installed
if ! command -v podman &> /dev/null; then
    log_error "podman is not installed!"
    log_info "Install with: sudo dnf install podman (Fedora/RHEL) or sudo apt install podman (Debian/Ubuntu)"
    exit 1
fi

# Parse command
COMMAND="${1:-help}"

case "$COMMAND" in
    build)
        build_image
        ;;
    start)
        start_container
        ;;
    stop)
        stop_container
        ;;
    restart)
        restart_container
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    test)
        run_tests
        ;;
    clean)
        clean_all
        ;;
    deploy)
        full_deploy
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $COMMAND"
        echo ""
        show_help
        exit 1
        ;;
esac

exit 0
