"""
Output Layer

- Export ke Excel (.xlsx) via pandas + openpyxl
- Return bytes (untuk Streamlit download_button)
"""

from __future__ import annotations

import io
from typing import List, Dict, Any

import pandas as pd

import config


def export_rows_to_excel_bytes(rows: List[Dict[str, Any]]) -> bytes:
    df = pd.DataFrame(rows, columns=config.OUTPUT_SCHEMA)
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="products")
    return bio.getvalue()

