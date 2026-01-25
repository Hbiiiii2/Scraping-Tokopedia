# Tokopedia Product Reference Extraction Tool

Aplikasi GUI berbasis Streamlit untuk mengekstrak referensi produk dari Tokopedia dengan menggunakan browser automation (Playwright).

## ⚠️ PERINGATAN PENTING

### Legal & Ethical Considerations
- **Hormati Terms of Service Tokopedia**: Pastikan penggunaan tool ini sesuai dengan kebijakan Tokopedia
- **Rate Limiting**: Tool ini menggunakan delay dan retry logic, namun tetap gunakan dengan bijak
- **Personal Use**: Tool ini dirancang untuk penggunaan pribadi/research, bukan untuk scraping massal
- **Legal Liability**: Pengguna bertanggung jawab penuh atas penggunaan tool ini

### Technical Warnings
- **Selector Fragility**: Selector CSS/XPath dapat berubah sewaktu-waktu karena Tokopedia melakukan update UI
- **Maintenance Required**: Tool ini memerlukan maintenance berkala untuk mengupdate selector jika terjadi perubahan
- **Anti-Bot Detection**: Tokopedia memiliki sistem anti-bot yang dapat memblokir akses jika terdeteksi pola scraping
- **No Guarantees**: Tidak ada jaminan bahwa scraping akan selalu berhasil, terutama jika ada perubahan struktur website

## Prerequisites

- Python 3.11.x
- pip (Python package manager)

## Installation

1. Clone atau download repository ini

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
playwright install chromium
```

4. (Opsional) Konfigurasi environment variables

Repo ini menggunakan `python-dotenv` untuk membaca file `.env` bila ada, namun **file template `.env.example` tidak disertakan** di workspace ini (dibatasi oleh policy environment). Kamu bisa membuat `.env` manual di root project dengan isi seperti:

```text
HEADLESS_MODE=true
BROWSER_TIMEOUT=30000
PAGE_LOAD_TIMEOUT=10000
MAX_PRODUCTS_PER_KEYWORD=5
MAX_CANDIDATES_TO_COLLECT=30
MIN_DELAY_SECONDS=2
MAX_DELAY_SECONDS=5
MAX_RETRIES=3
RETRY_DELAY_SECONDS=2
DOWNLOAD_IMAGES=true
IMAGE_TIMEOUT=10
MAX_IMAGE_SIZE_MB=5
OUTPUT_DIR=output
IMAGES_DIR=images
LOGS_DIR=logs
```

## Usage

Jalankan aplikasi Streamlit:
```bash
streamlit run app.py
```

Aplikasi akan terbuka di browser default pada `http://localhost:8501`

## Input Methods

1. **Excel (.xlsx)**: Upload file Excel dengan kolom "keyword" atau baris pertama berisi keyword
2. **CSV (.csv)**: Upload file CSV dengan kolom "keyword" atau baris pertama berisi keyword
3. **Manual Input**: Ketik keyword langsung di text field (satu per baris)

## Output

- **Excel File**: File `.xlsx` dengan struktur data produk
- **Image Folder**: Folder `images/` yang diorganisir per keyword

## Project Structure

```
.
├── app.py                 # Streamlit GUI application
├── config.py             # Configuration management
├── layers/
│   ├── __init__.py
│   ├── input_layer.py    # Input processing (CSV/Excel/manual)
│   ├── search_layer.py   # Tokopedia search scraping
│   ├── detail_layer.py   # Product detail extraction
│   ├── ranking_layer.py  # Product filtering & ranking
│   ├── image_layer.py    # Image download & management
│   ├── normalization_layer.py  # Data normalization
│   └── output_layer.py   # Excel export
├── utils/
│   ├── __init__.py
│   ├── browser.py        # Playwright browser management
│   ├── logger.py         # Logging setup
│   └── helpers.py        # Utility functions
├── output/               # Output Excel files
├── images/               # Downloaded product images
├── logs/                 # Application logs
├── requirements.txt
├── .env.example
└── README.md
```

## Maintenance Notes

Jika scraping gagal, kemungkinan besar selector CSS/XPath sudah berubah. Periksa:
1. File `layers/search_layer.py` - selector untuk search results
2. File `layers/detail_layer.py` - selector untuk product details
3. Gunakan browser DevTools untuk inspect elemen baru
4. Update selector di kode sesuai dengan struktur DOM baru

## Troubleshooting

- **Browser tidak terbuka**: Pastikan Playwright sudah terinstall dengan benar
- **Selector tidak ditemukan**: Periksa apakah struktur HTML Tokopedia sudah berubah
- **Rate limiting**: Tambahkan delay lebih lama di `.env`
- **Image download gagal**: Periksa koneksi internet dan URL gambar

## License

Tool ini dibuat untuk tujuan edukasi dan research. Gunakan dengan tanggung jawab.
