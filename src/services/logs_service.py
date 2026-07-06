import logging
import os
from typing import Dict, Any
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from ..config.settings import LOG_FILE

logger = logging.getLogger(__name__)

class LogsService:
    """Service class for log management operations"""
    
    @staticmethod
    def _tail_file(filepath: str, lines: int) -> str:
        """Efficiently read last N lines from a file without loading entire file into memory"""
        try:
            with open(filepath, 'rb') as f:
                # Seek to end of file
                f.seek(0, 2)
                file_size = f.tell()

                # If file is empty or lines is 0
                if file_size == 0 or lines == 0:
                    return ""

                # Read file in chunks from end
                block_size = 4096
                blocks = []
                lines_found = 0
                bytes_read = 0

                # Read backwards until we find enough lines
                while bytes_read < file_size and lines_found < lines:
                    # Calculate how much to read
                    read_size = min(block_size, file_size - bytes_read)
                    f.seek(file_size - bytes_read - read_size)
                    block = f.read(read_size)
                    blocks.append(block)
                    bytes_read += read_size

                    # Count newlines in this block
                    lines_found += block.count(b'\n')

                # Combine blocks (they're in reverse order)
                data = b''.join(reversed(blocks))

                # Decode and split into lines
                text = data.decode('utf-8', errors='replace')
                all_lines = text.split('\n')

                # Return last N lines
                return '\n'.join(all_lines[-lines:])

        except Exception as e:
            logger.error(f"Error in _tail_file: {e}")
            raise

    @staticmethod
    async def get_logs(lines: int = 100) -> PlainTextResponse:
        """Get the contents of the log file (efficiently reads last N lines)"""
        log_file_path = LOG_FILE

        try:
            if not os.path.exists(log_file_path):
                return PlainTextResponse(
                    content="Log file not found. The application may not have started yet or logging is not configured properly.",
                    status_code=404
                )

            # Use efficient tail method instead of reading entire file
            log_content = LogsService._tail_file(log_file_path, lines)

            return PlainTextResponse(
                content=log_content,
                media_type="text/plain"
            )

        except PermissionError:
            logger.error(f"Permission denied accessing log file: {log_file_path}")
            raise HTTPException(
                status_code=403,
                detail="Permission denied accessing log file"
            )
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error reading log file: {str(e)}"
            )
    
    @staticmethod
    async def get_log_info() -> Dict[str, Any]:
        """Get information about the log file"""
        log_file_path = LOG_FILE
        
        try:
            if not os.path.exists(log_file_path):
                return {
                    "exists": False,
                    "message": "Log file not found"
                }
            
            stat = os.stat(log_file_path)
            
            return {
                "exists": True,
                "file_path": os.path.abspath(log_file_path),
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "last_modified": stat.st_mtime,
                "lines_available": "Use /api/logs?lines=N to view last N lines"
            }
            
        except Exception as e:
            logger.error(f"Error getting log info: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"Error getting log information: {str(e)}"
            )