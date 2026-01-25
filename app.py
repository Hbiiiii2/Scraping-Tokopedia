"""
Streamlit GUI: Tokopedia Product Reference Extraction Tool

Catatan arsitektur:
- Pipeline sinkron (sync Playwright) supaya sederhana di Streamlit.
- Semua scraping lewat Playwright (Tokopedia JS-rendered).
"""

from __future__ import annotations

# FIX: Apply nest_asyncio di awal untuk compatibility dengan Streamlit + Playwright
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass  # nest_asyncio optional, tapi recommended

# FIX Windows: pastikan event loop policy mendukung subprocess (Playwright).
# Ini penting karena Streamlit jalan di thread yang kadang memakai SelectorEventLoop.
try:
    import sys
    import asyncio
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
except Exception:
    pass

import io
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import pandas as pd
import streamlit as st

import config
from utils.logger import logger
from utils.browser import create_page, close_browser, reset_browser

# Test logger
logger.info("=" * 50)
logger.info("Tokopedia Scraper Application Started")
logger.info("=" * 50)
from utils.helpers import normalize_keywords
from layers.input_layer import load_keywords_from_upload, load_keywords_from_manual
from layers.search_layer import search_candidates, TokopediaBlockedError
from layers.detail_layer import scrape_product_detail
from layers.ranking_layer import rank_and_select_top_n
from layers.image_layer import download_product_image
from layers.normalization_layer import normalize_output_row
from layers.output_layer import export_rows_to_excel_bytes


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_pipeline(
    keywords: List[str],
    *,
    enable_image_download: bool,
    status_cb,
    progress_cb,
) -> tuple[List[Dict[str, Any]], Optional[bytes]]:
    """
    Jalankan end-to-end pipeline untuk banyak keyword.
    Mengembalikan list of output rows (schema wajib) + bytes excel.
    """
    all_rows: List[Dict[str, Any]] = []
    page = None

    try:
        status_cb("Menyiapkan browser...")
        logger.info("=" * 50)
        logger.info("PIPELINE: Starting browser setup...")
        logger.info(f"Timeout settings - Browser: {config.BROWSER_TIMEOUT}ms, Page: {config.PAGE_LOAD_TIMEOUT}ms")
        try:
            page = create_page()
            status_cb("✅ Browser siap!")
            logger.info("✅ PIPELINE: Browser ready, proceeding to scraping...")
        except Exception as e:
            error_msg = f"Gagal membuat browser: {str(e)}"
            logger.exception(error_msg)
            status_cb(f"❌ ERROR: {error_msg}")
            raise Exception(error_msg) from e

        for idx, kw in enumerate(keywords, start=1):
            status_cb(f"[{idx}/{len(keywords)}] Mulai keyword: '{kw}'")
            progress_cb((idx - 1) / max(len(keywords), 1))

            try:
                # 1) Search candidates (20-30)
                status_cb(f"  - Mencari produk untuk '{kw}'...")
                try:
                    candidates = search_candidates(page, kw, max_candidates=config.MAX_CANDIDATES_TO_COLLECT)
                except TokopediaBlockedError as be:
                    # Ini kondisi nyata: captcha/blocked. Beri instruksi jelas.
                    status_cb("  - ❌ Tokopedia meminta verifikasi / captcha.")
                    status_cb("  - 💡 Solusi: set `HEADLESS_MODE=false`, jalankan ulang, selesaikan captcha di browser, lalu retry.")
                    status_cb(f"  - 💾 Session akan disimpan ke `{config.STORAGE_STATE_FILE}` setelah berhasil.")
                    raise
                status_cb(f"  - Kandidat terkumpul: {len(candidates)}")
                
                if not candidates:
                    status_cb(f"  - ⚠️ Tidak ada kandidat ditemukan untuk '{kw}'")
                    continue

                # 2) Detail scraping untuk kandidat (batasi supaya tidak berat)
                status_cb(f"  - Mengambil detail produk ({len(candidates)} kandidat)...")
                detailed = []
                for c_i, cand in enumerate(candidates, start=1):
                    try:
                        status_cb(f"  - Detail [{c_i}/{len(candidates)}]: {cand.get('product_name','(no name)')[:50]}...")
                        detail = scrape_product_detail(page, cand["product_url"])
                        merged = {**cand, **detail}
                        merged["input_keyword"] = kw
                        merged["source_site"] = "tokopedia"
                        merged["scraped_at"] = _now_iso()
                        detailed.append(merged)
                    except Exception as e:
                        logger.warning(f"Detail scrape gagal: {cand.get('product_url')} | {e}")
                        status_cb(f"    ⚠️ Skip: {str(e)[:50]}...")
                        continue

                status_cb(f"  - Detail sukses: {len(detailed)}/{len(candidates)}")

                if not detailed:
                    status_cb(f"  - ⚠️ Tidak ada detail berhasil diambil untuk '{kw}'")
                    continue

                # 3) Rank & select top 5
                status_cb(f"  - Meranking produk...")
                top = rank_and_select_top_n(kw, detailed, top_n=config.MAX_PRODUCTS_PER_KEYWORD)
                status_cb(f"  - Top {len(top)} terpilih")

                # 4) Download image (opsional)
                if enable_image_download:
                    status_cb(f"  - Download gambar ({len(top)} produk)...")
                for t in top:
                    if not enable_image_download:
                        t["image_local_path"] = ""
                        continue
                    try:
                        # Download primary image
                        image_url = t.get("image_url", "")
                        if not image_url and "image_urls" in t and t["image_urls"]:
                            image_url = t["image_urls"][0]  # Use first image from list
                        
                        if image_url:
                            local_path = download_product_image(
                                keyword=kw,
                                product_name=t.get("product_name", ""),
                                image_url=image_url,
                            )
                            t["image_local_path"] = str(local_path) if local_path else ""
                        else:
                            t["image_local_path"] = ""
                    except Exception as e:
                        logger.warning(f"Download image gagal: {t.get('image_url')} | {e}")
                        t["image_local_path"] = ""

                # 5) Normalize output schema
                for t in top:
                    all_rows.append(normalize_output_row(t))
                
                status_cb(f"  - ✅ Selesai: {len(top)} produk untuk '{kw}'")

            except Exception as e:
                error_msg = f"Error saat memproses keyword '{kw}': {str(e)}"
                logger.exception(error_msg)
                status_cb(f"  - ❌ ERROR: {error_msg}")
                # Continue ke keyword berikutnya
                continue

            progress_cb(idx / max(len(keywords), 1))

        status_cb("Menyiapkan file Excel...")
        excel_bytes = export_rows_to_excel_bytes(all_rows)
        status_cb(f"✅ Pipeline selesai! Total {len(all_rows)} produk ditemukan.")
        return all_rows, excel_bytes

    except Exception as e:
        error_msg = f"Fatal error di pipeline: {str(e)}"
        logger.exception(error_msg)
        status_cb(f"❌ FATAL ERROR: {error_msg}")
        raise
    finally:
        status_cb("Menutup browser...")
        try:
            if page is not None:
                page.close()
        except Exception:
            pass
        try:
            close_browser()
        except Exception:
            pass
        status_cb("Browser ditutup.")


def main():
    st.set_page_config(page_title="Tokopedia Product Reference Extractor", layout="wide")
    st.title("Tokopedia Product Reference Extraction Tool")

    st.caption(
        "⚠️ Tokopedia JS-rendered + anti-bot. Selector bisa berubah; tool ini butuh maintenance berkala."
    )
    
    # Check dependencies
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        st.warning("⚠️ `nest-asyncio` belum terinstall. Install dengan: `pip install nest-asyncio`")
    
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        st.error("❌ Playwright belum terinstall. Install dengan: `pip install playwright && playwright install chromium`")
        return

    with st.sidebar:
        st.subheader("Input")
        uploaded = st.file_uploader("Upload CSV / Excel", type=["csv", "xlsx"])
        manual = st.text_area("Manual keyword (1 baris = 1 keyword)", height=180)

        st.subheader("Opsi")
        enable_image_download = st.toggle("Download gambar", value=config.DOWNLOAD_IMAGES)
        st.caption("Jika ON, gambar disimpan ke folder `images/<keyword>/`.")

        start = st.button("Mulai Scraping", type="primary")

    log_box = st.empty()
    progress = st.progress(0.0)

    logs: List[str] = []

    def status_cb(msg: str):
        logs.append(f"{datetime.now().strftime('%H:%M:%S')} | {msg}")
        # tampilkan tail supaya UI ringan
        log_box.text("\n".join(logs[-40:]))

    def progress_cb(v: float):
        progress.progress(min(max(v, 0.0), 1.0))

    if start:
        try:
            # Log start session
            logger.info("=" * 60)
            logger.info("NEW SCRAPING SESSION STARTED")
            logger.info("=" * 60)
            
            reset_browser()
            status_cb("Menyiapkan keyword...")
            logger.debug("Browser reset completed")

            keywords: List[str] = []
            if uploaded is not None:
                logger.info(f"Loading keywords from uploaded file: {uploaded.name}")
                keywords.extend(load_keywords_from_upload(uploaded))
            if manual.strip():
                logger.info(f"Loading keywords from manual input: {len(manual.splitlines())} lines")
                keywords.extend(load_keywords_from_manual(manual))

            keywords = normalize_keywords(keywords)
            logger.info(f"Normalized keywords: {keywords}")
            
            if not keywords:
                st.error("Tidak ada keyword yang valid.")
                status_cb("❌ Tidak ada keyword yang valid.")
                logger.warning("No valid keywords found")
                return

            status_cb(f"Total keyword: {len(keywords)}")
            status_cb("Memulai pipeline scraping...")
            logger.info(f"Starting pipeline with {len(keywords)} keywords: {keywords}")
            
            rows, excel_bytes = run_pipeline(
                keywords,
                enable_image_download=enable_image_download,
                status_cb=status_cb,
                progress_cb=progress_cb,
            )

            if rows:
                st.success(f"✅ Selesai! Total {len(rows)} produk ditemukan.")
                status_cb(f"✅ Selesai! Total {len(rows)} produk ditemukan.")

                df = pd.DataFrame(rows, columns=config.OUTPUT_SCHEMA)
                st.dataframe(df, use_container_width=True)

                if excel_bytes:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    st.download_button(
                        "📥 Download Excel (.xlsx)",
                        data=excel_bytes,
                        file_name=f"tokopedia_product_refs_{ts}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            else:
                st.warning("⚠️ Tidak ada produk yang ditemukan. Coba keyword lain atau check log untuk detail.")
                status_cb("⚠️ Tidak ada produk yang ditemukan.")

        except KeyboardInterrupt:
            status_cb("❌ Dibatalkan oleh user.")
            st.warning("Proses dibatalkan.")
        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Pipeline error: {error_msg}")
            status_cb(f"❌ ERROR: {error_msg}")
            st.error(f"❌ Gagal: {error_msg}")
            st.info("💡 Tips: Check log di `logs/scraper.log` untuk detail error. Pastikan `nest-asyncio` sudah terinstall.")


if __name__ == "__main__":
    main()

