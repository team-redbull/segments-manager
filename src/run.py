import uvicorn
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import setup_logging, SERVER_HOST, SERVER_PORT

# Setup logging
logger = setup_logging()
logger.info("Starting Segments Manager server...")

# Start the server
uvicorn.run(
    "src.app:app",
    host=SERVER_HOST,
    port=SERVER_PORT,
    log_level="info"
)