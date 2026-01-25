"""
Utility functions untuk berbagai operasi umum.
"""
import re
import time
import random
from pathlib import Path
from slugify import slugify
from typing import List, Optional
from utils.logger import logger

def normalize_keyword(keyword: str) -> str:
    """
    Normalize keyword: lowercase, trim, remove special symbols.
    
    Args:
        keyword: Input keyword string
        
    Returns:
        Normalized keyword string
    """
    if not keyword:
        return ""
    
    # Trim whitespace
    keyword = keyword.strip()
    
    # Convert to lowercase
    keyword = keyword.lower()
    
    # Remove special characters (keep alphanumeric and spaces)
    keyword = re.sub(r'[^\w\s-]', '', keyword)
    
    # Replace multiple spaces with single space
    keyword = re.sub(r'\s+', ' ', keyword)
    
    return keyword.strip()


def normalize_keywords(keywords: List[str]) -> List[str]:
    """
    Normalize list of keywords.
    
    Args:
        keywords: List of keyword strings
        
    Returns:
        List of normalized keywords (unique, non-empty)
    """
    normalized = [normalize_keyword(kw) for kw in keywords if kw]
    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for kw in normalized:
        if kw and kw not in seen:
            seen.add(kw)
            unique.append(kw)
    
    return unique


def random_delay(min_seconds: float = None, max_seconds: float = None):
    """
    Add random delay untuk menghindari rate limiting.
    
    Args:
        min_seconds: Minimum delay in seconds
        max_seconds: Maximum delay in seconds
    """
    import config
    
    min_delay = min_seconds or config.MIN_DELAY_SECONDS
    max_delay = max_seconds or config.MAX_DELAY_SECONDS
    
    delay = random.uniform(min_delay, max_delay)
    logger.debug(f"Random delay: {delay:.2f} seconds")
    time.sleep(delay)


def create_safe_filename(text: str, max_length: int = 100) -> str:
    """
    Create safe filename dari text.
    
    Args:
        text: Input text
        max_length: Maximum length of filename
        
    Returns:
        Safe filename string
    """
    # Use slugify untuk create safe filename
    filename = slugify(text, max_length=max_length)
    
    # Fallback jika slugify menghasilkan empty string
    if not filename:
        filename = re.sub(r'[^\w\s-]', '', text)[:max_length]
        filename = re.sub(r'\s+', '_', filename)
    
    return filename or "unnamed"


def extract_price_number(price_text: str) -> Optional[float]:
    """
    Extract numeric price dari text (e.g., "Rp 150.000" -> 150000.0).
    
    Args:
        price_text: Price text string
        
    Returns:
        Numeric price value atau None jika tidak bisa di-parse
    """
    if not price_text:
        return None
    
    # Remove currency symbols and text
    price_clean = re.sub(r'[^\d.,]', '', str(price_text))
    
    # Handle Indonesian number format (dot as thousand separator)
    # Replace dots with empty string, then replace comma with dot for decimal
    price_clean = price_clean.replace('.', '').replace(',', '.')
    
    try:
        return float(price_clean)
    except (ValueError, AttributeError):
        logger.warning(f"Failed to parse price: {price_text}")
        return None


def extract_currency(price_text: str) -> str:
    """
    Extract currency symbol dari price text.
    
    Args:
        price_text: Price text string
        
    Returns:
        Currency string (default: "IDR")
    """
    if not price_text:
        return "IDR"
    
    price_text = str(price_text).upper()
    
    if "RP" in price_text or "RUPIAH" in price_text:
        return "IDR"
    elif "$" in price_text or "USD" in price_text:
        return "USD"
    elif "€" in price_text or "EUR" in price_text:
        return "EUR"
    
    return "IDR"  # Default


def validate_image_url(url: str) -> bool:
    """
    Validate image URL format.
    
    Args:
        url: Image URL string
        
    Returns:
        True jika URL valid, False otherwise
    """
    if not url:
        return False
    
    # Basic URL validation
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    return bool(url_pattern.match(url))
