# Setup & Installation Guide

## Prerequisites

- Python 3.11.x
- pip (Python package manager)
- Internet connection untuk download dependencies dan Playwright browsers

## Installation Steps

### 1. Clone atau Download Project

```bash
# Jika menggunakan git
git clone <repository-url>
cd Scraping

# Atau extract ZIP file ke folder Scraping
```

### 2. Create Virtual Environment (Recommended)

**Windows:**
```powershell
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright Browsers

```bash
playwright install chromium
```

**Catatan**: Ini akan download Chromium browser (~150MB) yang diperlukan untuk scraping.

### 5. Setup Environment Variables (Optional)

Copy `.env.example` ke `.env` dan sesuaikan jika perlu:

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

Atau buat file `.env` manual dengan isi:

```env
HEADLESS_MODE=true
BROWSER_TIMEOUT=30000
MAX_PRODUCTS_PER_KEYWORD=5
MAX_CANDIDATES_TO_COLLECT=30
MIN_DELAY_SECONDS=2
MAX_DELAY_SECONDS=5
DOWNLOAD_IMAGES=true
```

**Catatan**: Jika tidak ada file `.env`, aplikasi akan menggunakan default values dari `config.py`.

## Running the Application

### Start Streamlit App

```bash
streamlit run app.py
```

Aplikasi akan otomatis terbuka di browser default pada `http://localhost:8501`

### Alternative: Custom Port

```bash
streamlit run app.py --server.port 8502
```

## Testing

### Quick Test

1. Buka aplikasi di browser
2. Di sidebar, masukkan keyword manual:
   ```
   laptop
   smartphone
   ```
3. Klik "Mulai Scraping"
4. Tunggu proses selesai
5. Download Excel hasil

### Test dengan File Upload

1. Gunakan file `example_keywords.csv` yang sudah disediakan
2. Upload di sidebar
3. Klik "Mulai Scraping"

## Troubleshooting

### Error: "playwright not found"

**Solusi**: Install Playwright browsers:
```bash
playwright install chromium
```

### Error: "ModuleNotFoundError"

**Solusi**: Pastikan virtual environment aktif dan dependencies terinstall:
```bash
pip install -r requirements.txt
```

### Error: "Browser launch failed"

**Solusi**: 
1. Pastikan Playwright browsers sudah terinstall
2. Coba set `HEADLESS_MODE=false` di `.env` untuk debug
3. Check log di folder `logs/`

### Selector tidak ditemukan / Scraping gagal

**Solusi**: 
1. Ini normal - selector Tokopedia bisa berubah
2. Check log di `logs/scraper.log`
3. Update selector di `layers/search_layer.py` atau `layers/detail_layer.py`
4. Lihat dokumentasi di `ARCHITECTURE.md` untuk detail selector

### Rate Limiting / IP Blocked

**Solusi**:
1. Tambahkan delay lebih lama di `.env`:
   ```
   MIN_DELAY_SECONDS=5
   MAX_DELAY_SECONDS=10
   ```
2. Kurangi jumlah keyword per batch
3. Tunggu beberapa saat sebelum scrape lagi

### Image Download Gagal

**Solusi**:
1. Check koneksi internet
2. Pastikan folder `images/` writable
3. Check log untuk detail error
4. Bisa disable image download di toggle

## Project Structure

```
Scraping/
├── app.py                    # Streamlit GUI
├── config.py                 # Configuration
├── requirements.txt          # Dependencies
├── README.md                 # Main documentation
├── ARCHITECTURE.md           # Architecture details
├── SETUP.md                  # This file
├── .gitignore
├── layers/                   # Core scraping layers
│   ├── input_layer.py
│   ├── search_layer.py
│   ├── detail_layer.py
│   ├── ranking_layer.py
│   ├── image_layer.py
│   ├── normalization_layer.py
│   └── output_layer.py
├── utils/                    # Utilities
│   ├── browser.py
│   ├── helpers.py
│   └── logger.py
├── output/                   # Excel outputs (auto-created)
├── images/                   # Downloaded images (auto-created)
│   └── <keyword-slug>/
└── logs/                     # Application logs (auto-created)
    └── scraper.log
```

## Next Steps

1. **Read README.md**: Overview dan warnings penting
2. **Read ARCHITECTURE.md**: Detail implementasi dan maintenance
3. **Test dengan keyword sederhana**: Pastikan semua bekerja
4. **Monitor logs**: Check `logs/scraper.log` untuk issues
5. **Update selectors jika perlu**: Lihat dokumentasi selector di ARCHITECTURE.md

## Support

Jika ada masalah:
1. Check log di `logs/scraper.log`
2. Review error messages di Streamlit UI
3. Pastikan semua dependencies terinstall
4. Verify Playwright browsers sudah terinstall

## Production Deployment Notes

Untuk production:
1. Set `HEADLESS_MODE=true` di `.env`
2. Setup proper logging rotation
3. Monitor success rate
4. Setup alert untuk selector failures
5. Review rate limiting settings
6. Consider menggunakan proxy jika perlu
