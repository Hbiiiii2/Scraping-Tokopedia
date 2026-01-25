"""
Normalization Layer

Output schema (MANDATORY):
input_keyword
product_name
description
price
currency
image_url
image_local_path
store_name
product_url
source_site
scraped_at
"""

from __future__ import annotations

from typing import Dict, Any

import config
from utils.helpers import extract_price_number, extract_currency


def normalize_output_row(row: Dict[str, Any]) -> Dict[str, Any]:
    price_val = row.get("price")
    if not isinstance(price_val, (int, float)):
        price_val = extract_price_number(str(price_val))

    currency = row.get("currency") or extract_currency(str(row.get("price", "")))
    if not currency:
        currency = "IDR"

    out = {
        "input_keyword": (row.get("input_keyword") or "").strip(),
        "product_name": (row.get("product_name") or "").strip(),
        "description": (row.get("description") or "").strip(),
        "price": float(price_val) if price_val else None,
        "currency": currency,
        "image_url": (row.get("image_url") or "").strip(),
        "image_local_path": (row.get("image_local_path") or "").strip(),
        "store_name": (row.get("store_name") or "").strip(),
        "product_url": (row.get("product_url") or "").strip(),
        "source_site": (row.get("source_site") or "tokopedia").strip(),
        "scraped_at": (row.get("scraped_at") or "").strip(),
    }

    # enforce schema order keys exist
    for k in config.OUTPUT_SCHEMA:
        out.setdefault(k, "")

    return out

