"""
Configuration management untuk Tokopedia Scraper.
Menggunakan python-dotenv untuk load environment variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base directories
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / os.getenv("OUTPUT_DIR", "output")
IMAGES_DIR = BASE_DIR / os.getenv("IMAGES_DIR", "images")
LOGS_DIR = BASE_DIR / os.getenv("LOGS_DIR", "logs")

# Create directories if they don't exist
OUTPUT_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Browser settings
HEADLESS_MODE = os.getenv("HEADLESS_MODE", "true").lower() == "true"
BROWSER_TIMEOUT = int(os.getenv("BROWSER_TIMEOUT", "15000"))  # Reduced: 30s -> 15s
PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", "8000"))  # Reduced: 10s -> 8s

# Scraping settings
MAX_PRODUCTS_PER_KEYWORD = int(os.getenv("MAX_PRODUCTS_PER_KEYWORD", "5"))
MAX_CANDIDATES_TO_COLLECT = int(os.getenv("MAX_CANDIDATES_TO_COLLECT", "30"))
MIN_DELAY_SECONDS = float(os.getenv("MIN_DELAY_SECONDS", "1"))  # Reduced: 2s -> 1s
MAX_DELAY_SECONDS = float(os.getenv("MAX_DELAY_SECONDS", "3"))  # Reduced: 5s -> 3s

# Retry settings
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", "2"))

# Captcha/Blocking detection
SKIP_CAPTCHA_CHECK = os.getenv("SKIP_CAPTCHA_CHECK", "false").lower() == "true"

# Chrome Profile Settings (Optional)
# Jika diset, akan menggunakan persistent context (seperti user beneran)
CHROME_USER_DATA_DIR = os.getenv("CHROME_USER_DATA_DIR", "")
CHROME_PROFILE_DIRECTORY = os.getenv("CHROME_PROFILE_DIRECTORY", "Default")
CHROME_CHANNEL = os.getenv("CHROME_CHANNEL", "chrome")  # "chrome", "msedge", or "" for bundled chromium

# Image settings
DOWNLOAD_IMAGES = os.getenv("DOWNLOAD_IMAGES", "true").lower() == "true"
IMAGE_TIMEOUT = int(os.getenv("IMAGE_TIMEOUT", "10"))
MAX_IMAGE_SIZE_MB = int(os.getenv("MAX_IMAGE_SIZE_MB", "5"))

# Tokopedia URLs
TOKOPEDIA_BASE_URL = "https://www.tokopedia.com"
TOKOPEDIA_SEARCH_URL = f"{TOKOPEDIA_BASE_URL}/search"

# Persisted session (cookies/localStorage) untuk mengurangi captcha berulang.
# Akan dibuat otomatis setelah sesi berhasil.
STORAGE_STATE_FILE = os.getenv("STORAGE_STATE_FILE", "tokopedia_storage_state.json")

# Output schema
OUTPUT_SCHEMA = [
    "input_keyword",
    "product_name",
    "description",
    "price",
    "currency",
    "image_url",
    "image_local_path",
    "image_urls",
    "image_local_paths",
    "store_name",
    "product_url",
    "source_site",
    "scraped_at"
]

# Note: image_urls/image_local_paths disimpan sebagai teks (newline-separated)
