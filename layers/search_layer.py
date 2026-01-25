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
    try:
        return (locator.first.inner_text() or "").strip()
    except Exception:
        return ""


def _first_attr(locator, attr: str) -> str:
    try:
        return (locator.first.get_attribute(attr) or "").strip()
    except Exception:
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

    # Scroll untuk load lebih banyak kartu (lazy loading)
    logger.info("STEP: Scrolling to trigger lazy loading...")
    for i in range(8):  # Increased: 6 -> 8
        page.mouse.wheel(0, 1500)  # Increased scroll: 1200 -> 1500
        random_delay(1.0, 2.0)  # Increased delay: 0.6-1.3 -> 1.0-2.0
        if i % 2 == 0:
            logger.debug(f"Scrolled {i+1}/8 times...")
    
    # Wait extra untuk lazy loading
    logger.debug("Waiting for lazy-loaded content...")
    random_delay(2.0, 3.0)

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

    logger.info(f"STEP: Extracting data from {card_count} cards...")
    extracted_count = 0
    
    for i in range(min(card_count, max_candidates * 2)):  # ambil lebih, nanti diranking
        card = cards.nth(i)
        try:
            # Name - coba multiple selector dengan fallback
            name = ""
            name_selectors = [
                '[data-testid="spnSRPProdName"]',
                '[data-testid="lblProductName"]',
                'span[title]',
                'a[title]',
                'h3',
                'h2',
                'h1',
                'div[class*="name"]',
                'div[class*="title"]',
                'span[class*="name"]',
                'a[href*="/p/"]',  # Link text bisa jadi nama produk
            ]
            for name_sel in name_selectors:
                try:
                    name = _first_text(card.locator(name_sel))
                    if name and len(name.strip()) > 3:  # Minimal 3 karakter
                        break
                except Exception:
                    continue
            
            # Jika masih tidak ada name, coba ambil dari innerText card secara langsung
            if not name:
                try:
                    name = _first_text(card)
                    # Clean up - ambil baris pertama saja
                    if name:
                        name = name.split('\n')[0].strip()
                        if len(name) > 100:  # Terlalu panjang, mungkin bukan nama
                            name = ""
                except Exception:
                    pass
            
            # URL: biasanya ada <a> utama di card - coba multiple cara
            product_url = ""
            # Coba cari link ke product page
            url_selectors = [
                'a[href*="/p/"]',  # Product page link
                'a[href*="tokopedia.com"][href*="/p/"]',
                'a[href*="tokopedia.com"]',  # Any tokopedia link
                'a[href]',  # Any link
            ]
            for url_sel in url_selectors:
                try:
                    href = _first_attr(card.locator(url_sel), "href")
                    if href:
                        href_normalized = _normalize_url(href)
                        # Validasi: harus link ke produk Tokopedia
                        if "/p/" in href_normalized or ("tokopedia.com" in href_normalized and "product" in href_normalized.lower()):
                            product_url = href_normalized
                            break
                except Exception:
                    continue
            
            # Jika masih tidak ada URL, coba cari semua link di card
            if not product_url:
                try:
                    all_links = card.locator("a[href]")
                    for j in range(min(all_links.count(), 5)):  # Cek max 5 link pertama
                        href = _first_attr(all_links.nth(j), "href")
                        if href and "/p/" in href:
                            product_url = _normalize_url(href)
                            break
                except Exception:
                    pass
            
            # Price - coba multiple selector
            price_text = ""
            price_selectors = [
                '[data-testid="spnSRPProdPrice"]',
                '[data-testid="lblProductPrice"]',
                'span:has-text("Rp")',
                'div:has-text("Rp")',
                '[class*="price"]',
                '[class*="Price"]',
            ]
            for price_sel in price_selectors:
                try:
                    price_text = _first_text(card.locator(price_sel))
                    if price_text and "rp" in price_text.lower():
                        break
                except Exception:
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

            # Image URL - coba multiple attribute
            image_url = ""
            try:
                img_locator = card.locator("img")
                if img_locator.count() > 0:
                    img = img_locator.first
                    image_url = _normalize_url(
                        _safe_attr(img, "src") or 
                        _safe_attr(img, "data-src") or 
                        _safe_attr(img, "data-lazy-src") or
                        _safe_attr(img, "data-original")
                    )
            except Exception as img_err:
                logger.debug(f"Card {i+1}: Image extract failed: {img_err}")
                pass

            # Validasi: minimal harus ada name atau URL
            if not product_url and not name:
                logger.debug(f"Card {i}: Skipped - no name and no URL")
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

        if len(candidates) >= max_candidates:
            logger.info(f"Reached max candidates limit: {max_candidates}")
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

