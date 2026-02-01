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


def _srcset_pick_largest(srcset: str) -> str:
    """
    Pilih URL dari srcset dengan width descriptor terbesar (gambar resolusi tertinggi).
    Format: "url1 100w, url2 500w, url3 1200w" -> return url3.
    """
    if not srcset:
        return ""
    parts = [p.strip() for p in srcset.split(",") if p.strip()]
    if not parts:
        return ""
    best_url = ""
    best_w = 0
    for p in parts:
        tokens = p.split()
        if not tokens:
            continue
        url = tokens[0].strip()
        for t in tokens[1:]:
            t = t.strip().lower()
            if t.endswith("w") and t[:-1].isdigit():
                w = int(t[:-1])
                if w > best_w:
                    best_w = w
                    best_url = url
                break
        if not best_url and url:
            best_url = url
    return best_url or (parts[-1].split()[0].strip() if parts else "")


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


def _extract_store_name_from_next_data(detail_page):
    """Cari nama toko dari script#__NEXT_DATA__. Return str atau empty."""
    try:
        node = detail_page.locator("script#__NEXT_DATA__")
        if node.count() <= 0:
            return ""
        raw = (node.first.inner_text() or "").strip()
        if not raw:
            return ""
        data = json.loads(raw)
        for d in _walk_dicts(data):
            if not isinstance(d, dict):
                continue
            for k, v in d.items():
                if not k or not isinstance(k, str):
                    continue
                kl = k.lower()
                if not any(x in kl for x in ("shop", "store", "seller", "toko", "merchant")):
                    continue
                if isinstance(v, str) and 2 <= len(v.strip()) <= 150:
                    name = v.strip()
                    if name.lower() in ("tokopedia", "tokopedia.com", ""):
                        continue
                    return name
        return ""
    except Exception as e:
        logger.debug(f"__NEXT_DATA__ store name parse failed: {e}")
        return ""


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
                best = _srcset_pick_largest(_safe_attr(img, "srcset"))
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


# Tombol Next di PDP image detail (Tokopedia)
BTN_PDP_IMAGE_DETAIL_NEXT = 'button[data-testid="btnPDPImageDetailNext"]'
# Gambar utama di modal PDP (full-size, bukan thumbnail)
IMG_PDP_IMAGE_DETAIL = 'img[data-testid="PDPImageDetail"]'


def _upscale_tokopedia_image_url(url: str, target_size: int = 2000) -> str:
    """
    Tokopedia CDN pakai pattern: resize-jpeg:700:0 atau resize-jpeg:200:0.
    Ubah ke ukuran lebih besar (misal 2000) supaya download gambar HD.
    """
    if not url:
        return url
    # Pattern: resize-jpeg:NNN:0 atau resize-jpeg:NNN:NNN
    # Ganti angka pertama (width) ke target_size
    import re
    u = re.sub(r"resize-jpeg:\d+:", f"resize-jpeg:{target_size}:", url)
    u = re.sub(r"resize-webp:\d+:", f"resize-webp:{target_size}:", u)
    # Juga coba pattern /NNNxNNN/ di path
    u = re.sub(r"/\d{2,4}x\d{2,4}/", f"/{target_size}x{target_size}/", u)
    return u


def _get_current_detail_image_url(detail_page) -> str:
    """
    Ambil URL gambar yang sedang ditampilkan di viewer PDP (full-size).
    Prioritas: img[data-testid="PDPImageDetail"] di dalam modal.
    """
    # Prioritas 1: img utama di modal dengan data-testid="PDPImageDetail"
    img_selectors = [
        IMG_PDP_IMAGE_DETAIL,  # Selector tepat dari HTML Tokopedia
        '[data-testid="PDPImageDetail"]',
        'article[role="dialog"] img',
        '[role="dialog"] img[data-testid]',
        '[role="dialog"] img',
        '[aria-modal="true"] img',
        '[data-testid*="PDPDetailImage"] img',
        '[data-testid="imgPDPDetailMain"]',
        '[data-testid*="PDPImage"]',
    ]
    for sel in img_selectors:
        try:
            loc = detail_page.locator(sel)
            if loc.count() > 0:
                for i in range(min(loc.count(), 3)):
                    img = loc.nth(i)
                    try:
                        if img.is_visible():
                            src = _safe_attr(img, "src") or _safe_attr(img, "data-src")
                            srcset = _safe_attr(img, "srcset")
                            cand = _srcset_pick_largest(srcset) if srcset else src
                            cand = cand or src
                            if cand and _is_probable_image_url(_normalize_url(cand)):
                                # Upscale URL ke ukuran maksimal (2000px)
                                return _upscale_tokopedia_image_url(_normalize_url(cand))
                    except Exception:
                        continue
        except Exception:
            continue
    return ""


def _extract_fullsize_images_via_lightbox(detail_page) -> list[str]:
    """
    Logic: saat di product detail ->
    1. Pilih/klik foto produk (gambar pertama) supaya modal terbuka
    2. Ambil URL full-size dari img[data-testid="PDPImageDetail"], upscale ke 2000px
    3. Klik tombol Next (data-testid="btnPDPImageDetailNext")
    4. Ambil URL gambar yang baru tampil, simpan
    5. Ulangi sampai tombol Next tidak ada/disabled atau foto habis
    """
    urls: list[str] = []
    try:
        # 1) Pilih/klik foto produk supaya modal article[role="dialog"] terbuka
        main_img_selectors = [
            'button[data-testid*="thumbnail"]',
            '[data-testid*="PDPImage"]',
            '[data-testid*="PDPDetailImage"]',
            '[data-testid*="PDPMainImage"]',
            'img[data-testid*="PDP"]',
            'div[data-testid*="gallery"] img',
            'div[class*="gallery"] img',
            'div[class*="product-image"] img',
        ]
        main_img = None
        for sel in main_img_selectors:
            try:
                loc = detail_page.locator(sel)
                if loc.count() > 0:
                    main_img = loc.first
                    logger.debug(f"Pilih foto produk dengan selector: {sel}")
                    break
            except Exception:
                continue
        if not main_img:
            return []

        main_img.click(timeout=3000)
        random_delay(0.6, 1.0)

        # Tunggu modal terbuka (article[role="dialog"])
        try:
            detail_page.wait_for_selector('article[role="dialog"]', timeout=4000)
            logger.debug("Modal article[role='dialog'] terbuka")
        except Exception:
            logger.debug("Modal tidak terbuka, coba lanjut ambil gambar dari page")

        # 2) Ambil URL gambar dari img[data-testid="PDPImageDetail"] (full-size, upscale ke 2000px)
        current_url = _get_current_detail_image_url(detail_page)
        if current_url and _is_probable_image_url(current_url) and current_url not in urls:
            urls.append(current_url)
            logger.debug(f"Download foto 1: {current_url[:80]}...")

        # 3) Klik Next (btnPDPImageDetailNext) dan download sampai habis
        max_images = 30
        for idx in range(max_images - 1):
            try:
                next_btn = detail_page.locator(BTN_PDP_IMAGE_DETAIL_NEXT)
                if next_btn.count() == 0:
                    logger.debug("Tombol Next tidak ditemukan, selesai.")
                    break
                btn = next_btn.first
                if not btn.is_visible():
                    logger.debug("Tombol Next tidak visible, selesai.")
                    break
                # Disabled = sudah di foto terakhir
                disabled = btn.get_attribute("disabled")
                if disabled is not None:
                    logger.debug("Tombol Next disabled, selesai.")
                    break

                btn.click(timeout=2000)
                random_delay(0.4, 0.7)

                current_url = _get_current_detail_image_url(detail_page)
                if not current_url or not _is_probable_image_url(current_url):
                    continue
                if current_url in urls:
                    # Gambar sama = mungkin sudah di akhir, coba sekali lagi lalu stop
                    random_delay(0.3, 0.5)
                    current_url = _get_current_detail_image_url(detail_page)
                    if current_url and current_url not in urls:
                        urls.append(current_url)
                    break
                urls.append(current_url)
                logger.debug(f"Download foto {len(urls)}: {current_url[:80]}...")
            except Exception as e:
                logger.debug(f"Next/ambil URL gagal: {e}")
                break

        # Tutup modal (Escape atau klik tombol close)
        try:
            detail_page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            close_btn = detail_page.locator('article[role="dialog"] button[aria-label*="Tutup"], article[role="dialog"] button[aria-label*="Close"]')
            if close_btn.count() > 0 and close_btn.first.is_visible():
                close_btn.first.click(timeout=1000)
        except Exception:
            pass
        random_delay(0.2, 0.4)

        return urls[:max_images]
    except Exception as e:
        logger.debug(f"Lightbox full-size extraction failed: {e}")
        try:
            detail_page.keyboard.press("Escape")
        except Exception:
            pass
        return []


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

        # Store name (toko) - variasikan selector dan fallback __NEXT_DATA__
        logger.debug("Extracting store name...")
        store_selectors = [
            '[data-testid="llbPDPFooterShopName"]',
            '[data-testid="lblPDPDetailShopName"]',
            '[data-testid="llbPDPFooterShopName"] a',
            '[data-testid*="hopName"]',
            '[data-testid*="ShopName"]',
            'a[href*="tokopedia.com/"][href*="/shop/"]',
            '[class*="shop-name"]',
            '[class*="ShopName"]',
        ]
        store_name = ""
        for sel in store_selectors:
            try:
                loc = detail_page.locator(sel)
                if loc.count() > 0:
                    for i in range(min(loc.count(), 5)):
                        t = (loc.nth(i).inner_text() or "").strip()
                        if t and 2 <= len(t) <= 150 and t.lower() not in ("tokopedia", "tokopedia.com", "lihat toko"):
                            store_name = t
                            break
                if store_name:
                    break
            except Exception:
                continue
        if not store_name:
            store_name = _extract_store_name_from_next_data(detail_page)
        logger.debug(f"Store name extracted: {store_name[:50] if store_name else '(empty)'}...")

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
        
        # Image URLs - prioritaskan full-size (sama seperti saat user klik foto)
        logger.debug("Extracting image URLs (full-size via lightbox)...")
        image_urls: list[str] = []

        # 1) Klik gambar utama → buka lightbox → ambil URL full-size (tidak pecah saat zoom)
        lightbox_urls = _extract_fullsize_images_via_lightbox(detail_page)
        if lightbox_urls:
            image_urls.extend(lightbox_urls)
            logger.debug(f"Got {len(lightbox_urls)} full-size URLs from lightbox")
        if not image_urls:
            # 2) Fallback: __NEXT_DATA__ + DOM (pakai srcset terbesar)
            image_urls.extend(_extract_images_from_next_data(detail_page))
            for u in _extract_images_from_dom(detail_page):
                if u and u not in image_urls:
                    image_urls.append(u)

        # 3) Filter: buang URL yang jelas thumbnail (dimensi kecil di path)
        def _is_likely_thumbnail(u: str) -> bool:
            u_lower = u.lower()
            return "/100x100/" in u_lower or "/200x200/" in u_lower or "/150x150/" in u_lower
        image_urls = [u for u in image_urls if not _is_likely_thumbnail(u)] or image_urls

        # 4) Hard cap
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


