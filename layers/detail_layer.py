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


def _walk_dicts(obj: Any, depth: int = 0, max_depth: int = 15) -> Iterable[Dict]:
    """Walk nested dicts untuk cari field harga di __NEXT_DATA__."""
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v, depth + 1, max_depth)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dicts(v, depth + 1, max_depth)


def _extract_price_from_next_data(detail_page) -> tuple:
    """
    Cari price dari script#__NEXT_DATA__ (Next.js).
    Return (price: Optional[float], currency: str).
    """
    try:
        node = detail_page.locator("script#__NEXT_DATA__")
        if node.count() <= 0:
            return (None, "IDR")
        raw = (node.first.inner_text() or "").strip()
        if not raw:
            return (None, "IDR")
        data = json.loads(raw)

        # Nama kunci yang sering dipakai Tokopedia untuk harga
        price_keys = (
            "price", "priceInt", "priceValue", "productPrice", "finalPrice",
            "amount", "value", "harga", "basePrice", "originalPrice",
            "sellPrice", "formattedPrice", "product_price", "price_range",
        )
        for d in _walk_dicts(data):
            if not isinstance(d, dict):
                continue
            for k, v in d.items():
                if not k or not isinstance(k, str):
                    continue
                kl = k.lower()
                if not any(pk in kl for pk in ("price", "amount", "harga", "value")):
                    continue
                # Numerik
                if isinstance(v, (int, float)):
                    if 100 <= v <= 1e13:  # kisaran IDR
                        return (float(v), "IDR")
                # String berformat "Rp 12.345" atau "12500"
                if isinstance(v, str) and v.strip():
                    num = extract_price_number(v)
                    if num and 100 <= num <= 1e13:
                        return (num, extract_currency(v))
        return (None, "IDR")
    except Exception as e:
        logger.debug(f"__NEXT_DATA__ price parse failed: {e}")
        return (None, "IDR")


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

        # Price: variasikan selector dan fallback ke __NEXT_DATA__
        logger.debug("Extracting price...")
        price_selectors = [
            '[data-testid="lblPDPDetailProductPrice"]',
            '[data-testid="lblProductPrice"]',
            '[data-testid="lblPDPDetailProductPrice"]',
            '[data-testid*="rice"]',
            '[data-testid*="Price"]',
            'span[class*="price"]',
            'div[class*="price"]',
            'div[class*="Price"]',
            'p:has-text("Rp")',
            'div:has-text("Rp")',
        ]
        price_text = ""
        for sel in price_selectors:
            try:
                loc = detail_page.locator(sel)
                if loc.count() > 0:
                    # Coba beberapa elemen; ambil yang berisi angka harga valid
                    for i in range(min(loc.count(), 5)):
                        t = (loc.nth(i).inner_text() or "").strip()
                        if t and ("Rp" in t or "rp" in t.lower()) and any(c.isdigit() for c in t):
                            num = extract_price_number(t)
                            if num and 100 <= num <= 1e13:
                                price_text = t
                                break
                    if price_text:
                        break
            except Exception:
                continue
        price = extract_price_number(price_text) if price_text else None
        currency = extract_currency(price_text) if price_text else "IDR"
        # Fallback: ambil dari __NEXT_DATA__
        if price is None:
            price, currency = _extract_price_from_next_data(detail_page)
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


