"""
Detail Scraping Layer

Tujuan:
- Kunjungi halaman produk kandidat
- Ekstrak: description, price, currency, image_url, store_name, product_name (fallback)

Risiko produksi:
- Halaman bisa memunculkan interstitial (captcha/redirect).
- Konten bisa lazy-loaded; gunakan wait_for_selector + fallback.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Any, Iterable

from utils.logger import logger
from tenacity import retry, stop_after_attempt, wait_exponential

import config
from utils.helpers import random_delay, extract_price_number, extract_currency


def _safe_text(locator) -> str:
    try:
        return (locator.first.inner_text() or "").strip()
    except Exception:
        return ""


def _safe_attr(locator, attr: str) -> str:
    try:
        return (locator.first.get_attribute(attr) or "").strip()
    except Exception:
        return ""


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return config.TOKOPEDIA_BASE_URL + url
    return url


_IMG_EXT_RE = re.compile(r"\.(?:png|jpe?g|webp)(?:$|\?)", re.IGNORECASE)


def _is_probable_image_url(url: str) -> bool:
    if not url:
        return False
    u = url.strip()
    if not (u.startswith("http://") or u.startswith("https://") or u.startswith("//")):
        return False
    if _IMG_EXT_RE.search(u):
        return True
    # Tokopedia cache URL kadang tidak punya ekstensi yang jelas
    if "images.tokopedia.net" in u or "/img/" in u:
        return True
    return False


def _srcset_pick_best(srcset: str) -> str:
    if not srcset:
        return ""
    parts = [p.strip() for p in srcset.split(",") if p.strip()]
    if not parts:
        return ""
    last = parts[-1]
    return last.split(" ")[0].strip()


def _walk_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def _extract_images_from_next_data(detail_page) -> list[str]:
    """
    Tokopedia PDP biasanya Next.js. Banyak data gambar ada di script#__NEXT_DATA__.
    """
    urls: list[str] = []
    try:
        node = detail_page.locator("script#__NEXT_DATA__")
        if node.count() <= 0:
            return []
        raw = (node.first.inner_text() or "").strip()
        if not raw:
            return []
        data = json.loads(raw)
        for s in _walk_strings(data):
            if ("tokopedia" not in s) and ("images." not in s) and ("/img/" not in s):
                continue
            if _is_probable_image_url(s):
                u = _normalize_url(s)
                if u and u not in urls:
                    urls.append(u)
        # batasi supaya nggak kebanyakan asset non-gambar produk
        return urls[:30]
    except Exception as e:
        logger.debug(f"NEXT_DATA image parse failed: {e}")
        return []


def _extract_images_from_dom(detail_page) -> list[str]:
    """
    Fallback: ambil dari DOM (gallery/thumbnail).
    """
    urls: list[str] = []
    selectors = [
        'button[data-testid*="thumbnail"] img',
        '[data-testid*="Thumbnail"] img',
        'img[data-testid*="PDPImage"]',
        '[data-testid*="PDPImage"] img',
        "div.css-pefdcn img",
        "img[srcset]",
        "img[src]",
    ]

    for sel in selectors:
        try:
            imgs = detail_page.locator(sel)
            n = imgs.count()
            if n <= 0:
                continue
            for i in range(min(n, 40)):
                img = imgs.nth(i)
                src = _safe_attr(img, "src") or _safe_attr(img, "data-src") or _safe_attr(img, "data-lazy-src")
                best = _srcset_pick_best(_safe_attr(img, "srcset"))
                cand = best or src
                if not cand:
                    continue
                cand = _normalize_url(cand)
                if _is_probable_image_url(cand) and cand not in urls:
                    urls.append(cand)
            if len(urls) >= 20:
                break
        except Exception:
            continue
    return urls


@retry(stop=stop_after_attempt(config.MAX_RETRIES), wait=wait_exponential(multiplier=1, min=1, max=8))
def scrape_product_detail(page, product_url: str) -> Dict[str, Any]:
    """
    Scrape product detail page.
    Menggunakan tab baru untuk setiap product (sesuai instruksi user).
    """
    logger.info(f"STEP: Opening product detail page: {product_url}")

    # Buka di tab baru (sesuai instruksi user)
    try:
        # Create new page/tab untuk product detail
        context = page.context
        detail_page = context.new_page()
        logger.debug("Created new tab for product detail")
    except Exception:
        # Fallback: gunakan page yang sama
        detail_page = page
        logger.debug("Using existing page (new tab creation failed)")

    try:
        detail_page.goto(product_url, wait_until="domcontentloaded", timeout=config.BROWSER_TIMEOUT)
        random_delay()

        # Tunggu elemen penting muncul
        logger.debug("Waiting for product title...")
        try:
            # Wait untuk h1 dengan selector spesifik sesuai instruksi user
            detail_page.wait_for_selector(
                'h1[data-testid="lblPDPDetailProductName"], h1.css-j63za0',
                timeout=config.PAGE_LOAD_TIMEOUT
            )
        except Exception:
            # Fallback: tunggu h1 biasa
            try:
                detail_page.wait_for_selector("h1", timeout=config.PAGE_LOAD_TIMEOUT)
            except Exception:
                logger.warning("h1 tidak ditemukan cepat; DOM mungkin berubah atau halaman belum siap.")

        # Title - sesuai instruksi user: h1 dengan class css-j63za0 dan data-testid
        logger.debug("Extracting product title...")
        title = _safe_text(
            detail_page.locator(
                'h1[data-testid="lblPDPDetailProductName"].css-j63za0, '
                'h1[data-testid="lblPDPDetailProductName"], '
                'h1.css-j63za0, '
                'h1'
            )
        )
        logger.debug(f"Title extracted: {title[:60]}...")

        # Price: beberapa variasi testid; fallback teks "Rp"
        logger.debug("Extracting price...")
        price_text = _safe_text(
            detail_page.locator(
                '[data-testid="lblPDPDetailProductPrice"], [data-testid="lblProductPrice"], div:has-text("Rp")'
            )
        )
        price = extract_price_number(price_text)
        currency = extract_currency(price_text)
        logger.debug(f"Price extracted: {price} {currency}")

        # Store name (toko)
        logger.debug("Extracting store name...")
        store_name = _safe_text(
            detail_page.locator(
                '[data-testid="llbPDPFooterShopName"], [data-testid="lblPDPDetailShopName"], a[href*="tokopedia.com/"]'
            )
        )

        # Description - sesuai instruksi user: div[role="tabpanel"]
        logger.debug("Extracting description...")
        desc = ""
        desc_selectors = [
            'div[role="tabpanel"]',  # PRIORITY sesuai instruksi user
            '[data-testid="lblPDPDescriptionProduk"]',
            '[data-testid="lblPDPDescription"]',
            'div[data-testid*="description"]',
            'div[class*="description"]',
        ]
        for desc_sel in desc_selectors:
            try:
                desc = _safe_text(detail_page.locator(desc_sel))
                if desc and len(desc.strip()) > 10:  # Minimal 10 karakter
                    logger.debug(f"Description found with selector: {desc_sel}")
                    break
            except Exception:
                continue
        
        # Image URLs - ambil SEMUA foto dari detail (gallery/thumbnail/next-data)
        logger.debug("Extracting image URLs...")
        image_urls: list[str] = []

        # 1) Prefer __NEXT_DATA__ (paling sering lengkap)
        image_urls.extend(_extract_images_from_next_data(detail_page))

        # 2) Tambahkan dari DOM (thumbnail/gallery)
        for u in _extract_images_from_dom(detail_page):
            if u and u not in image_urls:
                image_urls.append(u)

        # 3) Hard cap
        image_urls = image_urls[:20]
        
        # Ambil image pertama sebagai primary image_url (untuk backward compatibility)
        img_url = image_urls[0] if image_urls else ""

        logger.info(f"✅ Detail extracted - Title: {title[:50]}..., Images: {len(image_urls)}")

        return {
            "product_name": title,
            "description": desc,
            "price": price,
            "currency": currency,
            "image_url": img_url,  # Primary image
            "image_urls": image_urls,  # All images
            "store_name": store_name,
        }
    
    finally:
        # Close detail page tab jika berbeda dari main page
        if detail_page != page:
            try:
                detail_page.close()
                logger.debug("Closed product detail tab")
            except Exception:
                pass


