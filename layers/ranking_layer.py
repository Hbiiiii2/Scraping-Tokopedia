"""
Filtering & Ranking Layer

Heuristik sederhana (tanpa AI/NLP):
- Relevance: overlap token keyword vs product_name
- Completeness: field penting terisi (name, price, url, store, image, desc)
- Price sanity: buang outlier pakai IQR (kalau cukup data), fallback rule-based

Keluaran: top N (maks 5) product dict.
"""

from __future__ import annotations

import math
import re
from typing import List, Dict, Any, Tuple


def _tokenize(s: str) -> List[str]:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return [t for t in s.split(" ") if t]


def _relevance_score(keyword: str, name: str) -> float:
    kw_t = set(_tokenize(keyword))
    nm_t = set(_tokenize(name))
    if not kw_t or not nm_t:
        return 0.0
    inter = len(kw_t & nm_t)
    union = len(kw_t | nm_t)
    return inter / union


def _completeness_score(p: Dict[str, Any]) -> float:
    fields = ["product_name", "price", "product_url", "store_name", "image_url", "description"]
    score = 0
    for f in fields:
        v = p.get(f)
        if v is None:
            continue
        if isinstance(v, (int, float)) and v > 0:
            score += 1
        elif isinstance(v, str) and v.strip():
            score += 1
    return score / len(fields)


def _extract_prices(products: List[Dict[str, Any]]) -> List[float]:
    out = []
    for p in products:
        v = p.get("price")
        if isinstance(v, (int, float)) and v and v > 0:
            out.append(float(v))
    return out


def _iqr_bounds(values: List[float]) -> Tuple[float, float]:
    # simple percentile (no numpy)
    vals = sorted(values)
    if len(vals) < 4:
        return (0.0, float("inf"))

    def pct(p: float) -> float:
        k = (len(vals) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return vals[int(k)]
        return vals[f] * (c - k) + vals[c] * (k - f)

    q1 = pct(0.25)
    q3 = pct(0.75)
    iqr = q3 - q1
    low = max(0.0, q1 - 1.5 * iqr)
    high = q3 + 1.5 * iqr
    return low, high


def rank_and_select_top_n(keyword: str, products: List[Dict[str, Any]], *, top_n: int = 5) -> List[Dict[str, Any]]:
    if not products:
        return []

    prices = _extract_prices(products)
    low, high = _iqr_bounds(prices)

    filtered = []
    for p in products:
        price = p.get("price")
        if isinstance(price, (int, float)) and price > 0:
            # outlier filter, tapi jangan terlalu agresif kalau data sedikit
            if len(prices) >= 8 and (price < low or price > high):
                continue
            # fallback hard bounds
            if price < 500 or price > 200_000_000:
                continue
        filtered.append(p)

    scored = []
    for p in filtered:
        rel = _relevance_score(keyword, p.get("product_name", ""))
        comp = _completeness_score(p)
        # Bobot: relevance dominan, completeness sebagai tie-breaker
        score = (0.75 * rel) + (0.25 * comp)
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:top_n]]

