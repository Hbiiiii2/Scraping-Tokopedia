"""
Output Layer

- Export ke Excel (.xlsx) via pandas + openpyxl
- Return bytes (untuk Streamlit download_button)
- Kolom product_url diberi lebar cukup agar link panjang bisa dibuka/dibaca penuh
"""

from __future__ import annotations

import io
from typing import List, Dict, Any

import pandas as pd
from openpyxl.utils import get_column_letter

import config


def export_rows_to_excel_bytes(rows: List[Dict[str, Any]]) -> bytes:
    df = pd.DataFrame(rows, columns=config.OUTPUT_SCHEMA)
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="products")
        ws = writer.book["products"]
        # Set lebar kolom agar isi terbaca; product_url lebar besar supaya link panjang bisa dibuka/dibaca penuh
        product_url_col_idx = config.OUTPUT_SCHEMA.index("product_url") + 1
        for col_idx, _ in enumerate(config.OUTPUT_SCHEMA, start=1):
            letter = get_column_letter(col_idx)
            if col_idx == product_url_col_idx:
                ws.column_dimensions[letter].width = 100
            else:
                ws.column_dimensions[letter].width = min(50, max(12, 15))
    return bio.getvalue()

