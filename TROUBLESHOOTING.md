# Troubleshooting Guide

## Error: NotImplementedError di Playwright

### Gejala
```
NotImplementedError
File "asyncio/base_events.py", line 502, in _make_subprocess_transport
    raise NotImplementedError
```

### Penyebab
Playwright sync API tidak bekerja di Streamlit thread di Windows karena:
- Streamlit berjalan di thread terpisah
- Playwright sync API menggunakan greenlet yang memerlukan event loop
- Windows event loop di thread tidak support subprocess operations

### Solusi yang Sudah Diimplementasikan

1. **Install nest-asyncio** (sudah ditambahkan di requirements.txt):
```bash
pip install nest-asyncio
```

2. **Browser.py sudah di-update** untuk menggunakan `nest_asyncio.apply()` di awal

### Jika Masih Error

#### Solusi Alternatif 1: Install ulang Playwright browsers
```bash
playwright install chromium
```

#### Solusi Alternatif 2: Gunakan headless mode
Pastikan di `.env` atau `config.py`:
```python
HEADLESS_MODE=true
```

#### Solusi Alternatif 3: Restart Streamlit
Tutup dan buka ulang aplikasi Streamlit:
```bash
# Stop aplikasi (Ctrl+C)
# Lalu jalankan lagi
streamlit run app.py
```

#### Solusi Alternatif 4: Update Playwright
```bash
pip install --upgrade playwright
playwright install chromium
```

### Debug Steps

1. **Check log file**:
   - Buka `logs/scraper.log`
   - Cari error message terakhir
   - Perhatikan stack trace

2. **Test Playwright standalone**:
   Buat file test `test_playwright.py`:
   ```python
   from playwright.sync_api import sync_playwright
   
   with sync_playwright() as p:
       browser = p.chromium.launch(headless=True)
       page = browser.new_page()
       page.goto("https://www.tokopedia.com")
       print(page.title())
       browser.close()
   ```
   
   Jalankan: `python test_playwright.py`
   
   Jika ini error, masalahnya di Playwright installation, bukan di kode.

3. **Check Python version**:
   ```bash
   python --version
   ```
   Harus Python 3.11.x

4. **Check virtual environment**:
   Pastikan virtual environment aktif dan semua dependencies terinstall:
   ```bash
   pip list | grep playwright
   pip list | grep nest-asyncio
   ```

### Known Issues

1. **Windows Defender / Antivirus**: 
   - Bisa block Playwright browser launch
   - Tambahkan exception untuk folder project

2. **Firewall**:
   - Pastikan tidak block Playwright browser

3. **Multiple Streamlit instances**:
   - Tutup semua instance Streamlit sebelum run baru
   - Check port 8501 tidak digunakan

### Workaround Sementara

Jika semua solusi di atas tidak bekerja, gunakan approach manual:

1. Buat script Python terpisah (bukan Streamlit):
   ```python
   # manual_scraper.py
   from playwright.sync_api import sync_playwright
   import config
   
   with sync_playwright() as p:
       browser = p.chromium.launch(headless=True)
       # ... scraping code ...
   ```

2. Run script ini dari command line
3. Import hasil ke Streamlit untuk display

### Contact & Support

Jika masalah masih terjadi setelah mencoba semua solusi:
1. Check log file lengkap
2. Screenshot error message
3. Check Python version dan OS version
4. Coba di environment berbeda (Linux/Mac) jika memungkinkan
