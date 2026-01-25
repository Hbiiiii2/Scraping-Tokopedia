"""
Logging setup menggunakan loguru.
"""
import sys
from pathlib import Path
from loguru import logger as _base_logger

# Setup LOGS_DIR tanpa import config (avoid circular import)
BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Remove default handler
_base_logger.remove()

# Add console handler dengan warna
_base_logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True
)

# Add file handler dengan error handling
log_file = LOGS_DIR / "scraper.log"
try:
    _base_logger.add(
        str(log_file),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        enqueue=True,  # Thread-safe logging
        catch=True,    # Catch errors in logging
        backtrace=True,  # Include backtrace
        diagnose=True,  # Include diagnose info
    )
    # Test write - force flush
    _base_logger.info("Logger initialized successfully - file handler active")
    _base_logger.debug(f"Log file location: {log_file.absolute()}")
except Exception as e:
    # Fallback: hanya console logging
    _base_logger.warning(f"Failed to setup file logging: {e}. Using console only.")
    import traceback
    _base_logger.error(f"Logger setup error details: {traceback.format_exc()}")

# Export logger untuk digunakan di modul lain
logger = _base_logger
