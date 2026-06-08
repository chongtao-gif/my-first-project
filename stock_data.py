"""AKShare data layer with caching, retries, and multi-source fallbacks."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Callable

import akshare as ak
import pandas as pd


def _retry(fn: Callable[[], pd.DataFrame], retries: int = 3, delay: float = 2.0) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - surface upstream API errors
            last_error = exc
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    raise last_error  # type: ignore[misc]


def _normalize_spot(df: pd.DataFrame) -> pd.DataFrame:
    """Unify spot quotes from different AKShare sources."""
    rename_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "price",
        "涨跌额": "change",
        "涨跌幅": "pct_change",
        "成交量": "volume",
        "成交额": "amount",
        "今开": "open",
        "最高": "high",
        "最低": "low",
        "昨收": "prev_close",
        "换手率": "turnover",
        "市盈率-动态": "pe",
        "市净率": "pb",
        "总市值": "market_cap",
        "流通市值": "float_cap",
    }
    out = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}).copy()

    if "code" not in out.columns and "symbol" in out.columns:
        out["code"] = out["symbol"]

    out["code"] = out["code"].astype(str).str.lower()
    out["price"] = pd.to_numeric(out.get("price"), errors="coerce")
    out["pct_change"] = pd.to_numeric(out.get("pct_change"), errors="coerce")
    out["volume"] = pd.to_numeric(out.get("volume"), errors="coerce")
    out["amount"] = pd.to_numeric(out.get("amount"), errors="coerce")
    return out


def _fetch_spot_em() -> pd.DataFrame:
    return _normalize_spot(_retry(ak.stock_zh_a_spot_em))


def _fetch_spot_sina() -> pd.DataFrame:
    return _normalize_spot(_retry(ak.stock_zh_a_spot))


@lru_cache(maxsize=1)
def get_a_share_spot() -> tuple[pd.DataFrame, str]:
    """Return all A-share spot quotes and the data source label."""
    errors: list[str] = []
    for label, fetcher in (
        ("东方财富", _fetch_spot_em),
        ("新浪财经", _fetch_spot_sina),
    ):
        try:
            return fetcher(), label
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
    raise RuntimeError("无法获取行情数据。\n" + "\n".join(errors))


def to_tx_symbol(code: str) -> str:
    """Convert user input to Tencent/Sina symbol, e.g. 600000 -> sh600000."""
    code = code.strip().lower().replace(".", "")
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def to_plain_code(symbol: str) -> str:
    symbol = symbol.strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if symbol.startswith(prefix):
            return symbol[len(prefix) :]
    return symbol


def _normalize_hist(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "换手率": "turnover",
    }
    out = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}).copy()
    if "date" not in out.columns and "日期" in df.columns:
        out["date"] = df["日期"]
    out["date"] = pd.to_datetime(out["date"])
    for col in ("open", "close", "high", "low", "volume", "amount"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.sort_values("date").reset_index(drop=True)


def get_stock_history(
    code: str,
    days: int = 180,
    adjust: str = "qfq",
) -> tuple[pd.DataFrame, str]:
    """Fetch daily K-line history with source fallbacks."""
    plain = to_plain_code(code)
    tx_symbol = to_tx_symbol(plain)
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    errors: list[str] = []

    try:
        df = _retry(
            lambda: ak.stock_zh_a_hist(
                symbol=plain,
                period="daily",
                start_date=start,
                end_date=end,
                adjust=adjust,
            )
        )
        return _normalize_hist(df), "东方财富"
    except Exception as exc:  # noqa: BLE001
        errors.append(f"东方财富: {exc}")

    try:
        df = _retry(
            lambda: ak.stock_zh_a_hist_tx(
                symbol=tx_symbol,
                start_date=start,
                end_date=end,
                adjust=adjust if adjust in {"qfq", "hfq"} else "",
            )
        )
        return _normalize_hist(df), "腾讯财经"
    except Exception as exc:  # noqa: BLE001
        errors.append(f"腾讯财经: {exc}")

    try:
        df = _retry(lambda: ak.stock_zh_a_daily(symbol=tx_symbol, adjust=adjust))
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        return _normalize_hist(df), "新浪财经"
    except Exception as exc:  # noqa: BLE001
        errors.append(f"新浪财经: {exc}")

    raise RuntimeError(f"无法获取 {plain} 历史行情。\n" + "\n".join(errors))


def search_stocks(query: str, spot_df: pd.DataFrame) -> pd.DataFrame:
    query = query.strip().lower()
    if not query:
        return spot_df.head(50)

    mask = spot_df["code"].str.contains(query, na=False)
    if "name" in spot_df.columns:
        mask = mask | spot_df["name"].astype(str).str.contains(query, case=False, na=False)
    plain = to_plain_code(query)
    if plain:
        mask = mask | spot_df["code"].str.endswith(plain, na=False)
    return spot_df[mask].head(100)


def format_large_number(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    if abs(value) >= 1e8:
        return f"{value / 1e8:.2f} 亿"
    if abs(value) >= 1e4:
        return f"{value / 1e4:.2f} 万"
    return f"{value:,.2f}"
