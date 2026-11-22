"""
Binance Spot ochiq (public) API'dan shamchalarni olish. Bot va backtest bir xil koddan foydalanadi.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional
import config

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
USER_AGENT = "LightweightQuantBot/3.1"


def _parse_kline(item: list) -> dict:
    open_dt = datetime.fromtimestamp(item[0] / 1000.0, tz=config.LOCAL_TZ)
    return {
        "open_time": int(item[0]),
        "close_time": int(item[6]),
        "date": open_dt.date(),
        "timestamp": open_dt.strftime("%Y-%m-%d %H:%M"),
        "open": float(item[1]),
        "high": float(item[2]),
        "low": float(item[3]),
        "close": float(item[4]),
    }


def fetch_klines(
    symbol: str,
    interval: str,
    limit: int = 500,
    start_time_ms: Optional[int] = None,
    timeout: float = 10.0,
) -> list[dict]:
    params = {"symbol": symbol, "interval": interval, "limit": min(int(limit), 1000)}
    if start_time_ms is not None:
        params["startTime"] = int(start_time_ms)
    url = f"{BINANCE_KLINES_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError(f"Binance kutilmagan javob qaytardi: {raw}")
    return [_parse_kline(item) for item in raw]


def split_closed_candles(candles: list[dict], now_ms: Optional[int] = None) -> tuple[list[dict], Optional[dict]]:
    """Shamchalarni yopilganlar va hozir shakllanayotgan (oxirgi) shamchaga ajratadi."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    closed = [c for c in candles if c["close_time"] < now_ms]
    forming = candles[-1] if candles and candles[-1]["close_time"] >= now_ms else None
    return closed, forming


def fetch_history(symbol: str, interval: str, days: int) -> list[dict]:
    """Bir necha so'rov bilan (har biri 1000 tagacha) oxirgi `days` kunlik shamchalarni yuklaydi."""
    start_ms = int((time.time() - days * 86400) * 1000)
    now_ms = int(time.time() * 1000)
    candles: list[dict] = []
    while True:
        batch = fetch_klines(symbol, interval, limit=1000, start_time_ms=start_ms)
        if not batch:
            break
        candles.extend(batch)
        start_ms = batch[-1]["open_time"] + 1
        if len(batch) < 1000 or start_ms >= now_ms:
            break
    closed, _ = split_closed_candles(candles, now_ms)
    return closed
