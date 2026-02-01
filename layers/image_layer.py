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
import re
from pathlib import Path
from typing import Optional, List

import requests
from utils.logger import logger
from slugify import slugify
from tenacity import retry, stop_after_attempt, wait_exponential

import config
from utils.helpers import validate_image_url

# Ukuran target untuk gambar (Tokopedia CDN pakai resize-jpeg:700:0, kita naikkan ke 2000)
IMAGE_UPSCALE_SIZE = 2000


def _upscale_image_url(url: str, target_size: int = IMAGE_UPSCALE_SIZE) -> str:
    """
    Coba ubah URL gambar thumbnail ke ukuran lebih besar agar download HD.
    Tokopedia CDN pakai pattern: resize-jpeg:700:0, resize-webp:200:0, dll.
    """
    if not url or not isinstance(url, str):
        return url or ""
    u = url.strip()
    # Tokopedia CDN: resize-jpeg:NNN:0 atau resize-webp:NNN:0 -> ubah ke target_size
    u = re.sub(r"resize-jpeg:\d+:", f"resize-jpeg:{target_size}:", u)
    u = re.sub(r"resize-webp:\d+:", f"resize-webp:{target_size}:", u)
    # Pola dimensi di path: /100x100/, /200x200/ -> ukuran lebih besar
    u = re.sub(r"/\d{2,4}x\d{2,4}/", f"/{target_size}x{target_size}/", u, flags=re.IGNORECASE)
    # Query params: w=100&h=100 -> w=target_size&h=target_size
    u = re.sub(r"([?&])w=\d+", f"\\1w={target_size}", u, flags=re.IGNORECASE)
    u = re.sub(r"([?&])h=\d+", f"\\1h={target_size}", u, flags=re.IGNORECASE)
    u = re.sub(r"([?&])width=\d+", f"\\1width={target_size}", u, flags=re.IGNORECASE)
    u = re.sub(r"([?&])height=\d+", f"\\1height={target_size}", u, flags=re.IGNORECASE)
    return u


def _keyword_dir(keyword: str) -> Path:
    kw_slug = slugify(keyword) or "keyword"
    d = config.IMAGES_DIR / kw_slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _deterministic_name(product_name: str, image_url: str) -> str:
    base = slugify(product_name)[:60] or "product"
    h = hashlib.md5((image_url or "").encode("utf-8")).hexdigest()[:10]
    return f"{base}_{h}.jpg"


def _product_dir(base_folder: str, keyword: str, product_name: str) -> Path:
    """
    Simpan semua foto per produk, dikelompokkan per keyword:
    images/<base_folder>/<keyword_slug>/<product_slug>/
    - base_folder = nama Excel (tanpa ekstensi) atau session
    - keyword_slug = klasifikasi per keyword
    - product_slug = 1 folder per produk
    """
    folder_slug = slugify(base_folder) or "session"
    kw_slug = slugify(keyword) or "keyword"
    prod_slug = slugify(product_name)[:80] or "product"
    d = config.IMAGES_DIR / folder_slug / kw_slug / prod_slug
    d.mkdir(parents=True, exist_ok=True)
    return d


@retry(stop=stop_after_attempt(config.MAX_RETRIES), wait=wait_exponential(multiplier=1, min=1, max=8))
def download_product_image(*, base_folder: str, keyword: str, product_name: str, image_url: str) -> Optional[Path]:
    if not image_url or not validate_image_url(image_url):
        return None
    # Up-scale URL ke resolusi lebih besar agar gambar tidak kecil
    image_url = _upscale_image_url(image_url)

    out_dir = _product_dir(base_folder, keyword, product_name)
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


def download_product_images(*, base_folder: str, keyword: str, product_name: str, image_urls: List[str]) -> List[Path]:
    """
    Download semua foto dari detail produk.
    Return list path yang berhasil di-download.
    Simpan ke: images/<base_folder>/<keyword_slug>/<product_slug>/
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

    out_dir = _product_dir(base_folder, keyword, product_name)
    saved: List[Path] = []

    for idx, url in enumerate(urls, start=1):
        if not validate_image_url(url):
            continue
        # Up-scale URL ke resolusi lebih besar agar gambar tidak kecil
        url = _upscale_image_url(url)

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

