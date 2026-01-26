"""
Image Download Layer

Kebutuhan:
- Download gambar via `requests`
- Simpan lokal dengan nama deterministik
- Folder per keyword: images/<keyword_slug>/
- Handle gagal download dengan aman (return None)
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, List

import requests
from utils.logger import logger
from slugify import slugify
from tenacity import retry, stop_after_attempt, wait_exponential

import config
from utils.helpers import validate_image_url


def _keyword_dir(keyword: str) -> Path:
    kw_slug = slugify(keyword) or "keyword"
    d = config.IMAGES_DIR / kw_slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _deterministic_name(product_name: str, image_url: str) -> str:
    base = slugify(product_name)[:60] or "product"
    h = hashlib.md5((image_url or "").encode("utf-8")).hexdigest()[:10]
    return f"{base}_{h}.jpg"


def _product_dir(keyword: str, product_name: str) -> Path:
    """
    Simpan semua foto per produk:
    images/<keyword_slug>/<product_slug>/
    """
    base = _keyword_dir(keyword)
    prod_slug = slugify(product_name)[:80] or "product"
    d = base / prod_slug
    d.mkdir(parents=True, exist_ok=True)
    return d


@retry(stop=stop_after_attempt(config.MAX_RETRIES), wait=wait_exponential(multiplier=1, min=1, max=8))
def download_product_image(*, keyword: str, product_name: str, image_url: str) -> Optional[Path]:
    if not image_url or not validate_image_url(image_url):
        return None

    out_dir = _keyword_dir(keyword)
    filename = _deterministic_name(product_name, image_url)
    out_path = out_dir / filename

    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": config.TOKOPEDIA_BASE_URL,
    }

    with requests.get(image_url, headers=headers, timeout=config.IMAGE_TIMEOUT, stream=True) as r:
        if r.status_code != 200:
            logger.debug(f"Image HTTP {r.status_code}: {image_url}")
            return None

        max_bytes = config.MAX_IMAGE_SIZE_MB * 1024 * 1024
        total = 0
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    logger.warning(f"Image terlalu besar, skip: {image_url}")
                    try:
                        out_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return None
                f.write(chunk)

    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    return None


def download_product_images(*, keyword: str, product_name: str, image_urls: List[str]) -> List[Path]:
    """
    Download semua foto dari detail produk.
    Return list path yang berhasil di-download.
    """
    if not image_urls:
        return []

    # Dedupe sambil menjaga urutan
    seen = set()
    urls: List[str] = []
    for u in image_urls:
        if not u or u in seen:
            continue
        seen.add(u)
        urls.append(u)

    out_dir = _product_dir(keyword, product_name)
    saved: List[Path] = []

    for idx, url in enumerate(urls, start=1):
        if not validate_image_url(url):
            continue

        # Nama file deterministik + prefix index biar urutan kebaca
        filename = _deterministic_name(product_name, url)
        out_path = out_dir / f"{idx:02d}_{filename}"

        if out_path.exists() and out_path.stat().st_size > 0:
            saved.append(out_path)
            continue

        # Reuse logic yang sama (streaming + max size), tapi ke out_path produk
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": config.TOKOPEDIA_BASE_URL,
        }

        try:
            with requests.get(url, headers=headers, timeout=config.IMAGE_TIMEOUT, stream=True) as r:
                if r.status_code != 200:
                    logger.debug(f"Image HTTP {r.status_code}: {url}")
                    continue

                max_bytes = config.MAX_IMAGE_SIZE_MB * 1024 * 1024
                total = 0
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            logger.warning(f"Image terlalu besar, skip: {url}")
                            try:
                                out_path.unlink(missing_ok=True)
                            except Exception:
                                pass
                            out_path = None
                            break
                        f.write(chunk)

            if out_path and out_path.exists() and out_path.stat().st_size > 0:
                saved.append(out_path)
        except Exception as e:
            logger.debug(f"Download image failed: {url} | {e}")
            continue

    return saved

