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

from typing import Dict, Any

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
        
        # Image URLs - sesuai instruksi user: div.css-pefdcn
        logger.debug("Extracting image URLs...")
        image_urls = []
        try:
            # Coba selector sesuai instruksi: div.css-pefdcn
            img_containers = detail_page.locator('div.css-pefdcn')
            img_count = img_containers.count()
            logger.debug(f"Found {img_count} image containers with css-pefdcn")
            
            # Extract images dari container
            for i in range(min(img_count, 10)):  # Max 10 images
                try:
                    container = img_containers.nth(i)
                    # Cari img di dalam container
                    img = container.locator("img").first
                    if img.count() > 0:
                        img_src = _safe_attr(img, "src") or _safe_attr(img, "data-src") or _safe_attr(img, "data-lazy-src")
                        if img_src:
                            img_url = _normalize_url(img_src)
                            if img_url and img_url not in image_urls:
                                image_urls.append(img_url)
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Image extraction with css-pefdcn failed: {e}")
        
        # Fallback: cari images dengan selector umum
        if not image_urls:
            try:
                imgs = detail_page.locator('img[data-testid*="PDPImage"], img[alt][src], img[srcset]')
                for i in range(min(imgs.count(), 5)):
                    img_src = _safe_attr(imgs.nth(i), "src")
                    if img_src:
                        img_url = _normalize_url(img_src)
                        if img_url and img_url not in image_urls:
                            image_urls.append(img_url)
            except Exception:
                pass
        
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


