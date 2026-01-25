# Arsitektur Tokopedia Product Reference Extraction Tool

## Overview

Tool ini dirancang dengan arsitektur modular berbasis layer untuk memisahkan tanggung jawab dan memudahkan maintenance. Setiap layer memiliki fungsi spesifik dan dapat diuji secara independen.

## Struktur Layer

### 1. Input Layer (`layers/input_layer.py`)

**Tujuan**: Memproses input keyword dari berbagai sumber

**Fungsi**:
- `load_keywords_from_upload()`: Parse CSV/Excel dari Streamlit upload
- `load_keywords_from_manual()`: Parse manual text input

**Fitur**:
- Auto-detect kolom keyword (keyword, keywords, input_keyword, q, query)
- Fallback ke kolom pertama jika tidak ditemukan
- Filter empty/NaN values

---

### 2. Search Layer (`layers/search_layer.py`)

**Tujuan**: Scrape hasil pencarian Tokopedia untuk mengumpulkan kandidat produk

**Fungsi**:
- `search_candidates()`: Kumpulkan 20-30 kandidat produk dari search results

**Strategi Selector (dengan fallback)**:
```python
# Primary selector
'[data-testid="master-product-card"]'

# Fallback selectors
'[data-testid="divProductWrapper"]'
'[data-testid="lstCL2ProductList"]'
'article'
```

**Fitur**:
- Scroll untuk trigger lazy-loading
- Multiple selector fallback
- Retry logic dengan tenacity
- Random delay untuk menghindari rate limiting
- Deduplication berdasarkan product_url

**⚠️ FRAGILITY WARNING**:
- Selector CSS/XPath Tokopedia berubah secara berkala
- `data-testid` relatif lebih stabil tapi tidak dijamin
- Perlu monitoring dan update selector secara berkala

---

### 3. Detail Scraping Layer (`layers/detail_layer.py`)

**Tujuan**: Extract informasi lengkap dari halaman detail produk

**Fungsi**:
- `scrape_product_detail()`: Extract semua field yang diperlukan

**Data yang di-extract**:
- Product name (title)
- Description
- Price (numeric)
- Currency
- Image URL
- Store name

**Strategi Selector**:
```python
# Product name
'[data-testid="lblPDPDetailProductName"]'
'h1'  # fallback

# Price
'[data-testid="lblPDPDetailProductPrice"]'
'div:has-text("Rp")'  # fallback

# Store name
'[data-testid="llbPDPFooterShopName"]'
'a[href*="tokopedia.com/"]'  # fallback
```

**⚠️ RISKS**:
- Halaman bisa menampilkan interstitial (captcha/redirect)
- Konten lazy-loaded memerlukan wait_for_selector
- Rate limiting jika terlalu cepat

---

### 4. Ranking Layer (`layers/ranking_layer.py`)

**Tujuan**: Filter dan rank produk untuk memilih top 5 terbaik

**Algoritma Scoring**:
1. **Relevance Score (75% weight)**:
   - Token overlap antara keyword dan product_name
   - Jaccard similarity: `intersection / union`

2. **Completeness Score (25% weight)**:
   - Cek field penting: name, price, url, store, image, description
   - Score = jumlah field terisi / total field

3. **Price Sanity Filter**:
   - IQR-based outlier detection (jika data >= 8)
   - Hard bounds: 500 - 200,000,000 IDR

**Output**: Top N produk (default: 5) berdasarkan composite score

---

### 5. Image Download Layer (`layers/image_layer.py`)

**Tujuan**: Download dan simpan gambar produk secara lokal

**Fungsi**:
- `download_product_image()`: Download single image dengan retry

**Struktur Folder**:
```
images/
  └── <keyword-slug>/
      └── <product-name>_<url-hash>.jpg
```

**Fitur**:
- Deterministic naming (hash-based untuk deduplication)
- Size limit (default: 5MB)
- Caching (skip jika file sudah ada)
- Retry logic dengan tenacity
- Graceful failure handling

---

### 6. Normalization Layer (`layers/normalization_layer.py`)

**Tujuan**: Normalize data ke output schema yang konsisten

**Fungsi**:
- `normalize_output_row()`: Ensure semua field sesuai schema

**Schema Output** (MANDATORY):
```python
[
    "input_keyword",
    "product_name",
    "description",
    "price",
    "currency",
    "image_url",
    "image_local_path",
    "store_name",
    "product_url",
    "source_site",
    "scraped_at"
]
```

**Normalization Rules**:
- Price: Convert ke numeric jika string
- Currency: Extract dari price text, default "IDR"
- String fields: Strip whitespace
- Missing fields: Set ke empty string

---

### 7. Output Layer (`layers/output_layer.py`)

**Tujuan**: Export data ke Excel format

**Fungsi**:
- `export_rows_to_excel_bytes()`: Generate Excel bytes untuk Streamlit download

**Fitur**:
- Menggunakan pandas + openpyxl
- Return bytes (tidak write ke disk langsung)
- Schema-aware column ordering

---

## Utility Modules

### Browser Management (`utils/browser.py`)

**Tujuan**: Manage Playwright browser lifecycle

**Fitur**:
- Singleton browser instance (reuse across requests)
- Random user agent rotation
- Anti-automation detection bypass
- Context management dengan proper cleanup

**Functions**:
- `init_browser()`: Initialize browser dengan retry
- `get_browser_context()`: Get/create context
- `create_page()`: Create new page
- `close_browser()`: Cleanup resources

---

### Helpers (`utils/helpers.py`)

**Utility Functions**:
- `normalize_keyword()`: Clean keyword text
- `normalize_keywords()`: Batch normalization + deduplication
- `random_delay()`: Random delay untuk rate limiting
- `extract_price_number()`: Parse price text ke numeric
- `extract_currency()`: Extract currency dari price text
- `validate_image_url()`: Validate URL format
- `create_safe_filename()`: Generate safe filename

---

### Logger (`utils/logger.py`)

**Setup**: Loguru dengan dual output
- Console: Colored, INFO level
- File: DEBUG level, rotation 10MB, retention 7 days

---

## Configuration (`config.py`)

**Environment Variables** (via `.env`):
- Browser settings (headless, timeout)
- Scraping settings (max products, delays)
- Retry settings
- Image settings
- Output directories

**Default Values**: Semua ada fallback jika `.env` tidak ada

---

## Streamlit App (`app.py`)

**Pipeline Flow**:
```
1. Load keywords (CSV/Excel/Manual)
2. Normalize keywords
3. For each keyword:
   a. Search candidates (20-30)
   b. Scrape details untuk setiap kandidat
   c. Rank & select top 5
   d. Download images (optional)
   e. Normalize output
4. Export to Excel
```

**UI Components**:
- File uploader (CSV/Excel)
- Manual text input
- Toggle image download
- Progress bar
- Status log
- Results table
- Download button

---

## Error Handling Strategy

### Retry Logic
- Menggunakan `tenacity` library
- Exponential backoff
- Max retries: 3 (configurable)

### Graceful Failures
- Setiap layer catch exception dan log warning
- Continue processing meskipun ada failure
- Return partial results jika memungkinkan

### Logging
- Debug level untuk troubleshooting
- Warning untuk non-critical failures
- Error untuk critical issues

---

## Maintenance Requirements

### Weekly Tasks
1. **Selector Validation**: Test apakah selector masih bekerja
2. **Success Rate Monitoring**: Track extraction success rate
3. **Error Log Review**: Check untuk pola error baru

### Monthly Tasks
1. **Update Selectors**: Jika ada perubahan DOM Tokopedia
2. **Review Rate Limiting**: Adjust delays jika perlu
3. **Update User Agents**: Rotate user agent list

### When Selectors Break
1. Inspect Tokopedia dengan browser DevTools
2. Identifikasi selector baru
3. Update di `search_layer.py` atau `detail_layer.py`
4. Test dengan sample keyword
5. Deploy update

---

## Performance Considerations

### Bottlenecks
1. **Network I/O**: Scraping detail pages (sequential)
2. **Image Downloads**: Sequential download (bisa di-parallelize)
3. **Browser Rendering**: JavaScript-heavy pages

### Optimization Opportunities
1. Parallel detail scraping (2-3 concurrent pages)
2. Async image downloads
3. Browser context reuse
4. Caching (images, search results)

---

## Security & Legal

### Rate Limiting
- Random delays: 2-5 seconds
- Max requests: ~30 per minute (conservative)
- Respect robots.txt (advisory)

### User Agent
- Rotate user agents
- Identify as bot (tidak spoof Googlebot)
- Set proper headers

### Data Usage
- ✅ Internal business intelligence
- ✅ Competitive analysis
- ✅ Price monitoring
- ❌ Republish tanpa attribution
- ❌ Train commercial ML models
- ❌ Sell extracted data

---

## Testing Strategy

### Manual Testing
1. Test dengan 1-2 keyword sederhana
2. Verify semua field terisi
3. Check image download
4. Validate Excel output

### Selector Testing
1. Run dengan headless=false untuk visual inspection
2. Check console untuk selector warnings
3. Monitor success rate

### Edge Cases
- Empty search results
- Product page tidak load
- Image download gagal
- Invalid price format
- Missing fields

---

## Known Limitations

1. **Selector Fragility**: Selector bisa break kapan saja
2. **Rate Limiting**: Tidak ada bypass guarantee
3. **Anti-Bot**: Tokopedia bisa detect dan block
4. **No Multi-Platform**: Hanya Tokopedia
5. **No AI/NLP**: Ranking sederhana, tidak pakai embeddings
6. **Sequential Processing**: Belum fully parallel

---

## Future Improvements

1. **Parallel Processing**: Async detail scraping
2. **Selector Versioning**: Multiple selector sets dengan fallback
3. **Monitoring Dashboard**: Track success rate, errors
4. **Auto Selector Update**: ML-based selector detection
5. **Caching Layer**: Redis untuk search results
6. **API Mode**: REST API selain Streamlit GUI
