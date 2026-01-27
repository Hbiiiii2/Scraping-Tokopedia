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
image_urls
image_local_paths
store_name
product_url
source_site
scraped_at
"""

from __future__ import annotations

from typing import Dict, Any

import config
from utils.helpers import extract_price_number, extract_currency


def _list_to_newline_text(v: Any) -> str:
    """
    Excel-friendly: list -> newline-separated text.
    """
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        return "\n".join([str(x).strip() for x in v if str(x).strip()])
    return str(v).strip()


def normalize_output_row(row: Dict[str, Any]) -> Dict[str, Any]:
    price_val = row.get("price")
    if not isinstance(price_val, (int, float)):
        price_val = extract_price_number(str(price_val)) if (price_val is not None and str(price_val).strip()) else None

    currency = row.get("currency") or extract_currency(str(row.get("price", "")))
    if not currency:
        currency = "IDR"

    # Pastikan price numeric untuk kolom Excel (termasuk 0)
    price_out = None if (price_val is None or price_val == "") else float(price_val)

    out = {
        "input_keyword": (row.get("input_keyword") or "").strip(),
        "product_name": (row.get("product_name") or "").strip(),
        "description": (row.get("description") or "").strip(),
        "price": price_out,
        "currency": currency,
        "image_url": (row.get("image_url") or "").strip(),
        "image_local_path": (row.get("image_local_path") or "").strip(),
        "image_urls": _list_to_newline_text(row.get("image_urls")),
        "image_local_paths": _list_to_newline_text(row.get("image_local_paths")),
        "store_name": (row.get("store_name") or "").strip(),
        "product_url": (row.get("product_url") or "").strip(),
        "source_site": (row.get("source_site") or "tokopedia").strip(),
        "scraped_at": (row.get("scraped_at") or "").strip(),
    }

    # enforce schema order keys exist
    for k in config.OUTPUT_SCHEMA:
        out.setdefault(k, "")

    return out

