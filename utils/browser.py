"""
Browser management menggunakan SeleniumBase + Playwright untuk bypass captcha/cloudflare.

Menggunakan SeleniumBase Stealthy Playwright Mode:
- Bypass captcha dan cloudflare detection
- Connect Playwright ke SeleniumBase via CDP (Chrome DevTools Protocol)
- Reference: https://github.com/seleniumbase/SeleniumBase/blob/master/examples/cdp_mode/playwright/ReadMe.md

Fallback ke Playwright biasa jika SeleniumBase tidak tersedia.
"""
import sys
import os
import asyncio
import nest_asyncio
# Apply nest_asyncio untuk allow nested event loops di Streamlit
nest_asyncio.apply()

import threading
from typing import Optional
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from fake_useragent import UserAgent
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import logger
import config

# Cek ketersediaan SeleniumBase di level module
try:
    from seleniumbase import sb_cdp
    _SELENIUMBASE_AVAILABLE = True
    logger.info("✅ SeleniumBase detected and available for anti-bot features.")
except ImportError:
    _SELENIUMBASE_AVAILABLE = False
    logger.warning("⚠️ SeleniumBase not found. Using standard Playwright with anti-bot measures. Install with 'pip install seleniumbase' for enhanced captcha bypass.")

# Global browser instance
_sb = None  # SeleniumBase instance
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_playwright = None
_lock = threading.RLock()


def get_user_agent() -> str:
    """Get random user agent untuk anti-bot."""
    try:
        ua = UserAgent()
        return ua.random
    except Exception:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _ensure_windows_proactor_event_loop() -> None:
    """Set Windows Proactor event loop policy untuk support subprocess."""
    if sys.platform != "win32":
        return

    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception as e:
        logger.debug(f"Failed to set WindowsProactorEventLoopPolicy: {e}")

    try:
        loop = asyncio.get_event_loop()
        if not isinstance(loop, asyncio.ProactorEventLoop):
            asyncio.set_event_loop(asyncio.ProactorEventLoop())
    except RuntimeError:
        # No event loop in this thread, create new one
        asyncio.set_event_loop(asyncio.ProactorEventLoop())


@retry(
    stop=stop_after_attempt(config.MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=config.RETRY_DELAY_SECONDS, max=8),
    retry=retry_if_exception_type((Exception,))
)
def init_browser() -> Browser:
    """
    Initialize browser dengan retry logic.
    Jika SeleniumBase tersedia, gunakan SeleniumBase + Playwright untuk bypass captcha/cloudflare.
    Jika tidak, gunakan Playwright biasa dengan anti-bot measures.
    
    Returns:
        Playwright Browser instance
    """
    global _browser, _playwright, _sb
    
    _ensure_windows_proactor_event_loop()
    
    with _lock:
        if _browser is None:
            logger.info("=" * 50)
            logger.info("STEP: Initializing browser...")
            logger.info(f"Headless mode: {config.HEADLESS_MODE}")
            logger.info(f"SeleniumBase available: {_SELENIUMBASE_AVAILABLE}")
            
            try:
                if _SELENIUMBASE_AVAILABLE:
                    # Mode: SeleniumBase + Playwright (enhanced anti-bot)
                    logger.info("Using SeleniumBase + Playwright mode (enhanced anti-bot)")
                    logger.debug("Starting SeleniumBase Chrome...")
                    
                    _sb = sb_cdp.Chrome(
                        headless=config.HEADLESS_MODE,
                        uc=True,  # Undetected Chrome
                        locale="id-ID",
                    )
                    
                    # Get CDP endpoint URL
                    endpoint_url = _sb.get_endpoint_url()
                    logger.debug(f"CDP endpoint: {endpoint_url}")
                    
                    # Connect Playwright ke SeleniumBase via CDP
                    logger.debug("Connecting Playwright to SeleniumBase via CDP...")
                    _playwright = sync_playwright().start()
                    _browser = _playwright.chromium.connect_over_cdp(endpoint_url)
                    
                    logger.info("✅ Browser initialized successfully (SeleniumBase + Playwright)")
                else:
                    # Mode: Playwright biasa dengan anti-bot measures
                    logger.info("Using standard Playwright mode with anti-bot measures")
                    logger.debug("Starting Playwright directly...")
                    
                    _playwright = sync_playwright().start()
                    logger.debug("Playwright started, launching browser...")
                    
                    _browser = _playwright.chromium.launch(
                        headless=config.HEADLESS_MODE,
                        args=[
                            '--no-sandbox',
                            '--disable-blink-features=AutomationControlled',
                            '--disable-dev-shm-usage',
                            '--window-size=1920,1080',
                            '--disable-infobars',
                            '--start-maximized',
                        ],
                        timeout=20000,  # 20 second timeout untuk browser launch
                    )
                    logger.info("✅ Browser initialized successfully (Standard Playwright)")
                    
            except Exception as e:
                logger.error(f"❌ Failed to initialize browser: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                # Cleanup jika gagal
                if _sb:
                    try:
                        _sb.quit()
                    except Exception:
                        pass
                    _sb = None
                if _playwright:
                    try:
                        _playwright.stop()
                    except Exception:
                        pass
                    _playwright = None
                raise
        
        return _browser


def get_browser_context() -> BrowserContext:
    """
    Get or create browser context.
    Jika menggunakan SeleniumBase, ambil dari existing session.
    ALWAYS use launch_persistent_context to ensure NON-INCOGNITO mode.
    
    Returns:
        BrowserContext instance
    """
    global _context, _browser, _playwright
    
    with _lock:
        if _context is None:
            # Check for SeleniumBase first
            if _SELENIUMBASE_AVAILABLE and _sb:
                # Logic SeleniumBase tetap sama (dia handle profilenya sendiri via arguments)
                 # ... (SeleniumBase logic relies on init_browser being called previously which sets _sb)
                 # But wait, init_browser is called inside here usually?
                 # Let's check the flow. init_browser() creates _sb.
                 pass

            # Prioritize Persistent Context (Playwright)
            # Tentukan path user data dir
            user_data_dir = config.CHROME_USER_DATA_DIR
            if not user_data_dir:
                # Fallback ke local 'user_data' folder agar tetap Persistent (bukan Incognito)
                user_data_dir = os.path.join(config.BASE_DIR, "user_data")
                logger.info(f"⚠️ No CHROME_USER_DATA_DIR set. Using local persistent dir: {user_data_dir}")
            
            # Buat directory jika belum ada (khusus local path)
            import shutil
            if not os.path.exists(user_data_dir):
                try:
                    os.makedirs(user_data_dir, exist_ok=True)
                except Exception as e:
                    logger.warning(f"Could not create user_data_dir, might fail if path invalid: {e}")

            logger.info("=" * 50)
            logger.info("STEP: Initializing PERSISTENT context (Non-Incognito)...")
            logger.info(f"User Data Dir: {user_data_dir}")
            
            if _playwright is None:
                _playwright = sync_playwright().start()
            
            user_agent = get_user_agent()
            
            # Args
            args = [
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--start-maximized',
            ]
            
            # Tambahkan profile directory arg jika diset (biasanya 'Default')
            if config.CHROME_PROFILE_DIRECTORY:
                    args.append(f'--profile-directory={config.CHROME_PROFILE_DIRECTORY}')

            try:
                # Launch Persistent Context
                # Note: launch_persistent_context creates a browser AND a context.
                # We map this to _context. _browser will be None (or we can assume context.browser)
                _context = _playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel=config.CHROME_CHANNEL,  # "chrome", "msedge", or None
                    headless=config.HEADLESS_MODE,
                    args=args,
                    user_agent=user_agent,
                    viewport={'width': 1920, 'height': 1080},
                    locale='id-ID',
                    timezone_id='Asia/Jakarta',
                    bypass_csp=True,
                    timeout=30000,
                )
                logger.info("✅ Persistent context launched successfully")
                
                # Apply stealth scripts
                _context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    window.navigator.chrome = {
                        runtime: {}
                    };
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['id-ID', 'id', 'en-US', 'en']
                    });
                """)
                
                # We don't need init_browser() call anymore for Playwright path
                # because launch_persistent_context handles browser creation.
                
            except Exception as e:
                logger.error(f"❌ Failed to launch persistent context: {e}")
                
                # Fallback extreme: Jika gagal persistent (misal permission error), 
                # baru fallback ke incognito biasa (tapi user minta NO incognito, jadi sebaiknya raise or warn)
                logger.warning("Attempting fallback to standard ephemeral context (INCOGNITO)...")
                
                browser = init_browser() # This calls standard launch
                _context = browser.new_context(
                     user_agent=user_agent,
                     viewport={'width': 1920, 'height': 1080},
                     locale='id-ID',
                     timezone_id='Asia/Jakarta',
                )
                logger.info("⚠️ Created Ephemeral Context (Incognito) as fallback.")

        return _context


def create_page() -> Page:
    """
    Create new page dari browser context.
    Jika menggunakan SeleniumBase dan ada existing page, gunakan itu.
    Jika tidak, buat page baru.
    
    Returns:
        Page instance
    """
    try:
        logger.info("STEP: Creating new page...")
        context = get_browser_context()
        
        # Cek apakah ada existing pages (dari SeleniumBase session)
        pages = context.pages
        if pages and _SELENIUMBASE_AVAILABLE:
            page = pages[0]
            logger.info("✅ Using existing page from SeleniumBase session")
        else:
            logger.debug("Creating new page from context...")
            page = context.new_page()
            logger.info("✅ New page created")
        
        # Set default timeout
        page.set_default_timeout(config.PAGE_LOAD_TIMEOUT)
        page.set_default_navigation_timeout(config.BROWSER_TIMEOUT)
        
        # Test koneksi ke Tokopedia homepage
        logger.info("STEP: Testing connection to Tokopedia homepage...")
        try:
            test_url = config.TOKOPEDIA_BASE_URL
            logger.debug(f"Navigating to: {test_url}")
            page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
            logger.info("✅ Successfully connected to Tokopedia homepage")
            
            # Check page status
            current_url = page.url
            page_title = page.title()
            logger.debug(f"Page title: {page_title}")
            logger.debug(f"Current URL: {current_url}")
            
            # Check for blocking/captcha on homepage
            has_captcha_form = page.locator('iframe[src*="captcha"], div[id*="captcha"], form[action*="captcha"]').count() > 0
            has_blocked_page = any(word in page_title.lower() or word in page.content().lower() for word in ['captcha', 'verify', 'blocked', 'access denied'])
            
            if has_captcha_form or has_blocked_page:
                logger.warning("⚠️ Possible blocking detected: captcha")
                if not config.SKIP_CAPTCHA_CHECK:
                    # Save storage state even if blocked, user can solve it manually
                    if not _SELENIUMBASE_AVAILABLE:
                        storage_state_path = config.BASE_DIR / config.STORAGE_STATE_FILE
                        context.storage_state(path=str(storage_state_path))
                        logger.info(f"Saved storage_state to: {storage_state_path}")
                    raise Exception(
                        "Tokopedia homepage diblokir atau meminta verifikasi (captcha). "
                        "Silakan jalankan aplikasi dengan HEADLESS_MODE=false, selesaikan captcha secara manual, "
                        "lalu restart aplikasi. Session akan disimpan."
                    )
            else:
                # Save storage state if connection is clean (hanya untuk Playwright biasa)
                if not _SELENIUMBASE_AVAILABLE:
                    storage_state_path = config.BASE_DIR / config.STORAGE_STATE_FILE
                    context.storage_state(path=str(storage_state_path))
                    logger.info(f"Saved storage_state to: {storage_state_path}")
            
            # Solve captcha jika ada (via SeleniumBase)
            if _SELENIUMBASE_AVAILABLE and _sb:
                try:
                    logger.debug("Checking for captcha via SeleniumBase...")
                    _sb.solve_captcha()  # SeleniumBase auto-solve captcha
                    logger.debug("Captcha check completed")
                except Exception as e:
                    logger.debug(f"Captcha solve attempt: {e}")
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to connect to Tokopedia homepage: {e}")
            # Don't raise here, let search_layer handle it
            pass
        
        logger.info(f"✅ Page ready with timeout: {config.PAGE_LOAD_TIMEOUT}ms")
        
        return page
        
    except Exception as e:
        logger.error(f"❌ Failed to create page: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise


def close_browser():
    """
    Close browser dan cleanup resources.
    """
    global _browser, _context, _playwright, _sb
    
    with _lock:
        try:
            if _context:
                try:
                    _context.close()
                except Exception:
                    pass
                _context = None
                logger.info("Browser context closed")
            
            if _browser:
                try:
                    _browser.close()
                except Exception:
                    pass
                _browser = None
                logger.info("Browser closed")
            
            if _playwright:
                try:
                    _playwright.stop()
                except Exception:
                    pass
                _playwright = None
                logger.info("Playwright stopped")
            
            if _sb:
                try:
                    _sb.quit()
                except Exception:
                    pass
                _sb = None
                logger.info("SeleniumBase closed")
                
        except Exception as e:
            logger.error(f"Error closing browser: {e}")


def reset_browser():
    """
    Reset browser instance (force new browser on next use).
    """
    global _browser, _context, _sb
    with _lock:
        close_browser()
        _browser = None
        _context = None
        _sb = None
        logger.info("Browser reset requested")
