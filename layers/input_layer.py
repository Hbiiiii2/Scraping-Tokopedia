"""
Input Layer
- Load keyword dari CSV/Excel upload Streamlit
- Load keyword dari manual text

Konvensi:
- CSV/Excel idealnya punya kolom bernama: keyword / keywords / input_keyword
- Jika tidak ada, ambil kolom pertama yang non-empty.
"""

from __future__ import annotations

import io
from typing import List

import pandas as pd


KEYWORD_COL_CANDIDATES = ["keyword", "keywords", "input_keyword", "q", "query"]


def _extract_keywords_from_df(df: pd.DataFrame) -> List[str]:
    if df is None or df.empty:
        return []

    cols_lower = {c.lower().strip(): c for c in df.columns}
    for c in KEYWORD_COL_CANDIDATES:
        if c in cols_lower:
            raw = df[cols_lower[c]].astype(str).tolist()
            return [x for x in raw if x and x.strip() and x.strip().lower() != "nan"]

    # fallback: kolom pertama
    first_col = df.columns[0]
    raw = df[first_col].astype(str).tolist()
    return [x for x in raw if x and x.strip() and x.strip().lower() != "nan"]


def load_keywords_from_upload(uploaded_file) -> List[str]:
    """
    uploaded_file: Streamlit UploadedFile
    """
    name = (uploaded_file.name or "").lower()
    data = uploaded_file.getvalue()

    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(data))
        return _extract_keywords_from_df(df)

    if name.endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(data))
        return _extract_keywords_from_df(df)

    return []


def load_keywords_from_manual(text: str) -> List[str]:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    return [ln for ln in lines if ln]

