"""
Search Layer (Tokopedia)

Prinsip robustness:
- Selector *HARUS* dianggap rapuh: gunakan beberapa fallback.
- Scroll untuk memicu lazy-load kartu produk.
- Kumpulkan 20-30 kandidat per keyword dari halaman hasil search.

Catatan:
- Tokopedia sering mengubah class name; `data-testid` relatif lebih stabil,
  tapi tidak dijamin selalu ada.
"""

from __future__ import annotations

import urllib.parse
from typing import Dict, Any, List, Optional

from utils.logger import logger
from tenacity import retry, stop_after_attempt, wait_exponential

import config
from utils.helpers import random_delay, extract_price_number, extract_currency
from pathlib import Path


class TokopediaBlockedError(Exception):
    """Raised when Tokopedia shows captcha / verification / blocked page."""
    pass


def build_search_url(keyword: str) -> str:
    q = urllib.parse.quote(keyword)
    # st=product penting agar fokus ke produk, bukan toko/etalase.
    return f"{config.TOKOPEDIA_SEARCH_URL}?st=product&q={q}"


def _first_text(locator) -> str:
    """Get first element text dengan optimasi untuk menghindari blocking lama."""
    try:
        # Cek count dulu (lebih cepat daripada langsung first)
        count = locator.count()
        if count == 0:
            return ""
        # Ambil text dari first element
        return (locator.first.inner_text() or "").strip()
    except Exception as e:
        # Skip jika error (element tidak ada atau page closed)
        return ""


def _first_attr(locator, attr: str) -> str:
    """Get first element attribute dengan optimasi untuk menghindari blocking lama."""
    try:
        # Cek count dulu (lebih cepat daripada langsung first)
        count = locator.count()
        if count == 0:
            return ""
        # Ambil attribute dari first element
        return (locator.first.get_attribute(attr) or "").strip()
    except Exception as e:
        # Skip jika error (element tidak ada atau page closed)
        return ""


def _safe_attr(locator, attr: str) -> str:
    """Safe get attribute - handle jika locator adalah single element bukan locator collection"""
    try:
        if hasattr(locator, 'first'):
            return (locator.first.get_attribute(attr) or "").strip()
        else:
            return (locator.get_attribute(attr) or "").strip()
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


_NON_PRODUCT_FIRST_SEGMENTS = {
    "search",
    "cart",
    "help",
    "promo",
    "discover",
    "blog",
    "about",
    "careers",
    "mitra",
    "seller",
    "admin",
    "events",
    "ta",
    "login",
    "register",
    "oauth",
    "category",
    "kategori",
}


def _looks_like_product_url(url: str) -> bool:
    """
    Tokopedia product URL umumnya seperti:
    - https://www.tokopedia.com/{shop_slug}/{product_slug}
    - kadang ada /p/ juga, tapi tidak selalu.
    """
    if not url:
        return False

    u = _normalize_url(url)
    try:
        parsed = urllib.parse.urlparse(u)
    except Exception:
        return False

    host = (parsed.netloc or "").lower()
    if "tokopedia.com" not in host:
        return False

    path = parsed.path or ""
    if not path or path == "/":
        return False

    segments = [s for s in path.split("/") if s]
    if not segments:
        return False

    # Support lama: /p/....
    if "p" in segments and "/p/" in path:
        return True

    # Umumnya product: /{shop}/{product}
    if len(segments) < 2:
        return False

    first = segments[0].lower()
    if first in _NON_PRODUCT_FIRST_SEGMENTS:
        return False

    # Segment kedua biasanya slug produk, bukan halaman umum
    second = segments[1].lower()
    if second in {"category", "kategori"}:
        return False

    # Filter halaman kategori/fitur umum yang bukan produk
    if "search" in path.lower():
        return False

    return True


def _pick_product_url_from_card(card) -> str:
    """
    Ambil URL produk dari card dengan cara yang robust.
    Jangan hardcode '/p/' karena Tokopedia sering pakai /{shop}/{product}.
    """
    try:
        links = card.locator("a[href]")
        link_count = links.count()
        # Scan beberapa link saja biar tetap cepat, tapi cukup robust
        for j in range(min(link_count, 25)):
            href = _first_attr(links.nth(j), "href")
            href_norm = _normalize_url(href)
            if _looks_like_product_url(href_norm):
                return href_norm
    except Exception:
        return ""
    return ""


@retry(stop=stop_after_attempt(config.MAX_RETRIES), wait=wait_exponential(multiplier=1, min=1, max=8))
def search_candidates(page, keyword: str, *, max_candidates: int = 30) -> List[Dict[str, Any]]:
    """
    Return list kandidat hasil search.
    Field minimal:
    - product_name
    - price (numeric)
    - currency
    - image_url
    - store_name
    - product_url
    """
    url = build_search_url(keyword)
    logger.info(f"Search URL: {url}")

    try:
        logger.info(f"STEP: Navigating to search URL: {url}")
        logger.debug(f"Timeout: {config.BROWSER_TIMEOUT}ms")
        
        # Try navigation dengan multiple wait strategies
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=config.BROWSER_TIMEOUT)
        except Exception as nav_error:
            logger.warning(f"domcontentloaded failed, trying networkidle: {nav_error}")
            try:
                page.goto(url, wait_until="networkidle", timeout=config.BROWSER_TIMEOUT)
            except Exception:
                # Last resort: just load, don't wait
                logger.warning("Both wait strategies failed, loading without wait...")
                page.goto(url, timeout=config.BROWSER_TIMEOUT, wait_until="commit")
        
        # Check page status
        current_url = page.url
        page_title = page.title()
        logger.info(f"✅ Page loaded successfully")
        logger.debug(f"Current URL: {current_url}")
        logger.debug(f"Page title: {page_title}")
        
        # Check untuk redirect atau blocking
        if "tokopedia.com" not in current_url.lower():
            logger.warning(f"⚠️ Unexpected redirect to: {current_url}")
        
        # Check untuk blocking page - lebih spesifik, jangan terlalu agresif
        if not config.SKIP_CAPTCHA_CHECK:
            page_content = page.content().lower()
            
            # Cek apakah benar-benar ada form captcha atau halaman blocked
            has_captcha_form = (
                'captcha' in page_content and 
                ('form' in page_content or 'challenge' in page_content or 'verify' in page_content)
            )
            has_blocked_page = (
                'access denied' in page_content or 
                'blocked' in page_content or
                'forbidden' in page_content
            )
            
            # Cek apakah ada produk di halaman (jika ada, berarti tidak blocked)
            has_products = False
            try:
                # Quick check: coba cari product card atau product link
                product_indicators = page.locator(
                    '[data-testid*="product"], [data-testid*="Product"], '
                    'a[href*="/p/"], a[href*="product"], '
                    '[class*="product"], [class*="Product"]'
                )
                if product_indicators.count() > 0:
                    has_products = True
                    logger.debug(f"Found {product_indicators.count()} product indicators - page seems OK")
            except Exception:
                pass
            
            # Hanya raise error jika benar-benar blocked DAN tidak ada produk
            if (has_captcha_form or has_blocked_page) and not has_products:
                logger.error("❌ Page appears to be blocked or showing captcha")
                logger.debug(f"Captcha form: {has_captcha_form}, Blocked: {has_blocked_page}, Has products: {has_products}")
                raise TokopediaBlockedError("Halaman diblokir atau meminta verifikasi (captcha)")
            elif has_captcha_form or has_blocked_page:
                # Ada warning tapi masih ada produk - continue dengan warning
                logger.warning("⚠️ Possible captcha/blocking detected, but products found - continuing...")
        else:
            logger.debug("Skipping captcha check (SKIP_CAPTCHA_CHECK=true)")
        
        logger.debug("Applying random delay...")
        random_delay()
        logger.debug("Delay completed")
        
    except TokopediaBlockedError:
        # Re-raise blocked error as-is
        raise
    except Exception as e:
        logger.error(f"❌ Failed to navigate to search URL: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Try to get screenshot for debugging
        try:
            screenshot_path = config.LOGS_DIR / f"error_screenshot_{int(__import__('time').time())}.png"
            page.screenshot(path=str(screenshot_path))
            logger.info(f"Screenshot saved to: {screenshot_path}")
        except Exception:
            pass
        
        raise Exception(f"Gagal membuka halaman search: {str(e)}") from e

    # Wait "something" that indicates product list is rendered.
    # Fallback 1: data-testid product card
    # Fallback 2: anchor tokopedia product links
    # Fallback 3: generic product container
    logger.info("STEP: Waiting for product list to load...")
    logger.debug(f"Timeout: {config.PAGE_LOAD_TIMEOUT}ms")
    product_list_loaded = False
    try:
        logger.debug("Trying selector: [data-testid='master-product-card']")
        page.wait_for_selector('[data-testid="master-product-card"]', timeout=config.PAGE_LOAD_TIMEOUT)
        product_list_loaded = True
        logger.info("✅ Found master-product-card selector")
    except Exception as e1:
        logger.debug(f"master-product-card not found: {e1}")
        try:
            logger.debug("Trying fallback selector: a[href*='tokopedia.com']")
            page.wait_for_selector('a[href*="tokopedia.com"]', timeout=config.PAGE_LOAD_TIMEOUT)
            product_list_loaded = True
            logger.info("✅ Found tokopedia link selector")
        except Exception as e2:
            logger.debug(f"tokopedia link not found: {e2}")
            try:
                # Fallback: tunggu body atau container apapun
                logger.debug("Trying fallback: body selector")
                page.wait_for_selector('body', timeout=5000)  # 5 second max
                logger.warning("⚠️ Using fallback: hanya menunggu body, selector produk mungkin berubah")
            except Exception as e3:
                logger.error(f"❌ Failed to load page content: {e3}")
                raise Exception("Halaman tidak bisa dimuat atau diblokir") from e3

    # Scroll untuk load kartu (lazy loading) - dikurangi karena hanya butuh 2 produk
    logger.info("STEP: Scrolling to trigger lazy loading (minimal scroll untuk 2 produk)...")
    for i in range(3):  # Reduced: hanya 3 scroll untuk 2 produk pertama
        page.mouse.wheel(0, 1000)  # Scroll lebih kecil
        random_delay(0.5, 1.0)  # Delay lebih pendek
        if i % 2 == 0:
            logger.debug(f"Scrolled {i+1}/3 times...")
    
    # Wait minimal untuk lazy loading
    logger.debug("Waiting for lazy-loaded content...")
    random_delay(1.0, 1.5)  # Reduced delay

    candidates: List[Dict[str, Any]] = []

    # Kandidat card (utama) - coba multiple selector dengan lebih agresif
    cards = None
    card_count = 0
    
    # List semua selector yang akan dicoba
    # PRIORITY: div[style*="display: contents"] sesuai instruksi user
    selectors_to_try = [
        ('div[style*="display: contents"]', 'div with display contents (PRIORITY)'),
        ('div[style="display: contents"]', 'div style="display: contents"'),
        ('[data-testid="master-product-card"]', 'master-product-card'),
        ('[data-testid="divProductWrapper"]', 'divProductWrapper'),
        ('[data-testid="lstCL2ProductList"]', 'lstCL2ProductList'),
        ('div[data-testid*="product"]', 'div with product testid'),
        ('a[href*="/p/"]', 'product links /p/'),
        ('a[href*="tokopedia.com"][href*="/p/"]', 'tokopedia product links'),
        ('div[class*="product-card"]', 'product-card class'),
        ('div[class*="ProductCard"]', 'ProductCard class'),
        ('article[data-testid]', 'article with testid'),
        ('div[class*="css-"][data-testid]', 'css class with testid'),
        ('a[href*="tokopedia.com"][href*="product"]', 'tokopedia product href'),
    ]
    
    logger.info("STEP: Trying multiple selectors to find product cards...")
    for selector, name in selectors_to_try:
        try:
            test_cards = page.locator(selector)
            test_count = test_cards.count()
            if test_count > 0:
                cards = test_cards
                card_count = test_count
                logger.info(f"✅ Found {card_count} cards with selector: {name} ({selector[:50]}...)")
                break
            else:
                logger.debug(f"  - {name}: 0 cards")
        except Exception as e:
            logger.debug(f"  - {name}: error - {str(e)[:50]}")
            continue
    
    # Jika masih tidak ada, coba screenshot untuk debugging
    if card_count == 0:
        logger.warning("⚠️ No product cards found with any selector")
        try:
            screenshot_path = config.LOGS_DIR / f"debug_no_cards_{int(__import__('time').time())}.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(f"📸 Debug screenshot saved: {screenshot_path}")
            
            # Coba ambil page HTML snippet untuk debugging
            try:
                page_html = page.content()[:2000]  # First 2000 chars
                logger.debug(f"Page HTML snippet: {page_html[:500]}...")
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Could not save screenshot: {e}")
        
        # Return empty list - jangan raise error, biar pipeline continue
        return []
    else:
        logger.info(f"✅ Total cards found: {card_count}")

    # Pastikan cards tidak None
    if cards is None:
        logger.warning("⚠️ Cards locator is None")
        return []

    logger.info(f"STEP: Extracting data from {card_count} cards (target: {max_candidates} produk)...")
    extracted_count = 0
    
    # Loop hanya sampai dapat max_candidates produk yang valid (untuk efisiensi)
    # Optimasi: cek lebih sedikit card karena kita hanya butuh 2 produk
    max_cards_to_check = min(card_count, max_candidates * 5)  # Cek max 10 cards untuk 2 produk
    for i in range(max_cards_to_check):
        card = cards.nth(i)
        try:
            # OPTIMASI: Cek URL dulu (lebih cepat) - tapi harus robust (tidak hanya '/p/')
            product_url = _pick_product_url_from_card(card)
            
            # Jika tidak ada URL di quick check, skip card ini (bukan produk valid)
            if not product_url:
                # Debug: tampilkan 1 href pertama (kalau ada) untuk bantu troubleshooting selector
                try:
                    first_href = _first_attr(card.locator("a[href]"), "href")
                    first_href = _normalize_url(first_href) if first_href else ""
                    logger.debug(
                        f"Card {i+1}/{card_count}: Skip cepat - tidak ada product URL. First href: '{first_href[:80]}...'"
                    )
                except Exception:
                    logger.debug(f"Card {i+1}/{card_count}: Skip cepat - tidak ada product URL")
                continue
            
            # Name - coba multiple selector dengan fallback (prioritaskan yang cepat)
            name = ""
            name_selectors = [
                '[data-testid="spnSRPProdName"]',  # Paling umum
                '[data-testid="lblProductName"]',
                'a[href]',  # Link text (cepat)
                'span[title]',
                'a[title]',
                'h3',
                'h2',
            ]
            for name_sel in name_selectors[:4]:  # Batasi hanya 4 selector pertama untuk speed
                try:
                    name = _first_text(card.locator(name_sel))
                    if name and len(name.strip()) > 3:  # Minimal 3 karakter
                        break
                except Exception:
                    continue
            
            # Jika masih tidak ada name, coba ambil dari innerText card secara langsung
            if not name:
                try:
                    # Coba ambil text dari link yang URL-nya mirip produk dulu (lebih cepat & akurat)
                    links = card.locator("a[href]")
                    for j in range(min(links.count(), 5)):
                        href = _normalize_url(_first_attr(links.nth(j), "href"))
                        if href and (_looks_like_product_url(href) or href == product_url):
                            name = _first_text(links.nth(j))
                            if name and len(name.strip()) > 3:
                                name = name.strip()
                                break
                    # Jika masih tidak ada, ambil dari card secara langsung
                    if not name:
                        name = _first_text(card)
                        # Clean up - ambil baris pertama saja
                        if name:
                            name = name.split('\n')[0].strip()
                            if len(name) > 100:  # Terlalu panjang, mungkin bukan nama
                                name = ""
                except Exception:
                    pass
            
            # URL sudah diambil di quick check di atas, tidak perlu cek lagi
            
            # Price - coba multiple selector (batasi untuk speed)
            price_text = ""
            price_selectors = [
                '[data-testid="spnSRPProdPrice"]',  # Paling umum
                '[data-testid="lblProductPrice"]',
                'span:has-text("Rp")',
            ]
            for price_sel in price_selectors[:3]:  # Batasi hanya 3 selector pertama
                try:
                    price_text = _first_text(card.locator(price_sel))
                    if price_text and "rp" in price_text.lower():
                        break
                except Exception:
                    continue

            # Heuristik: buang card non-produk yang sering kebaca "Kategori"
            if (not price_text) and name and name.strip().lower() in {"kategori", "category"}:
                logger.debug(f"Card {i+1}/{card_count}: Skip - bukan produk (name='{name}')")
                continue
            
            price = extract_price_number(price_text) if price_text else None
            currency = extract_currency(price_text) if price_text else "IDR"

            # Store name (di SRP kadang ada)
            store_name = ""
            store_selectors = [
                '[data-testid="spnSRPShopName"]',
                '[data-testid="lblShopName"]',
                'a[href*="tokopedia.com"][href*="/shop/"]',
                '[class*="shop"]',
                '[class*="store"]',
            ]
            for store_sel in store_selectors:
                try:
                    store_name = _first_text(card.locator(store_sel))
                    if store_name:
                        break
                except Exception:
                    continue

            # Image URL - coba multiple attribute (skip jika error, tidak critical)
            image_url = ""
            try:
                img_locator = card.locator("img")
                img_count = img_locator.count()
                if img_count > 0:
                    img = img_locator.first
                    # Coba ambil src dulu (paling umum)
                    image_url = _normalize_url(_safe_attr(img, "src") or "")
                    # Jika tidak ada, coba data-src
                    if not image_url:
                        image_url = _normalize_url(_safe_attr(img, "data-src") or "")
            except Exception as img_err:
                # Image tidak critical, skip saja
                pass

            # Validasi: minimal harus ada name atau URL
            if not product_url and not name:
                # Debug: coba ambil sedikit info dari card untuk debugging
                try:
                    card_text_preview = _first_text(card)
                    card_text_snippet = card_text_preview[:100] if card_text_preview else "(empty)"
                    logger.debug(f"Card {i+1}/{card_count}: Skipped - no name and no URL. Card preview: '{card_text_snippet}...' (mungkin bukan produk valid)")
                except Exception:
                    logger.debug(f"Card {i+1}/{card_count}: Skipped - no name and no URL (tidak bisa membaca card content)")
                continue
            
            # Jika tidak ada name, coba ambil dari URL atau gunakan placeholder
            if not name:
                # Coba extract dari URL
                if product_url:
                    # Extract dari URL seperti: /p/product-name/12345
                    parts = product_url.split("/")
                    if len(parts) > 0:
                        name = parts[-1].replace("-", " ").title()
                if not name:
                    name = f"Product {i+1}"

            extracted_count += 1
            logger.info(f"✅ Card {i+1}/{card_count}: Extracted - Name: '{name[:60]}', Price: {price}, URL: {product_url[:70]}...")
            
            candidates.append(
                {
                    "product_name": name,
                    "description": "",  # nanti di detail
                    "price": price,
                    "currency": currency,
                    "image_url": image_url,
                    "store_name": store_name,
                    "product_url": product_url,
                }
            )
        except Exception as e:
            logger.warning(f"❌ Card {i+1} parse gagal: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            continue

        # Early exit jika sudah dapat cukup produk valid
        if len(candidates) >= max_candidates:
            logger.info(f"✅ Reached max candidates limit: {max_candidates} produk valid ditemukan")
            break
    
    logger.info(f"✅ Extracted {extracted_count} products from {card_count} cards")
    logger.info(f"✅ Total candidates after extraction: {len(candidates)}")

    # Dedupe by product_url
    seen = set()
    uniq = []
    for c in candidates:
        u = c.get("product_url")
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(c)

    return uniq[:max_candidates]

