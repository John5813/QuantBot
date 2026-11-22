"""
Yengil (Lightweight) Algoritmik Strategiya Moduli.
VPS xotirasini tejash uchun og'ir kutubxonalarsiz (pure Python) yozilgan.

MUHIM: signal faqat YOPILGAN shamchalar bo'yicha hisoblanishi kerak. Hali shakllanayotgan
shamcha narxi har soniyada o'zgaradi va signal "miltillab" turadi (repaint).
"""

from typing import List, Optional
import config


def ema_series(prices: List[float], period: int) -> List[Optional[float]]:
    """Har bir nuqta uchun EMA qiymatlari (dastlabki period-1 ta nuqta uchun None)."""
    result: List[Optional[float]] = [None] * len(prices)
    if period <= 0 or len(prices) < period:
        return result
    multiplier = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    result[period - 1] = ema
    for i in range(period, len(prices)):
        ema = (prices[i] - ema) * multiplier + ema
        result[i] = ema
    return result


def calculate_ema(prices: List[float], period: int) -> Optional[float]:
    series = ema_series(prices, period)
    if not series or series[-1] is None:
        return None
    return round(series[-1], 4)


def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """Wilder usulidagi RSI."""
    if period <= 0 or len(prices) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(prices)):
        delta = prices[i] - prices[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def evaluate_entry_signal(close_prices: List[float]) -> tuple[bool, dict]:
    """
    Qat'iy 3 bosqichli filtr (faqat yopilgan shamchalar yopilish narxlari beriladi):
    1. Global trend o'suvchi bo'lishi shart (EMA 20 > EMA 50 va narx EMA 50 dan tepada)
    2. Narx qisqa muddatli arzonlashgan (pullback) zonasida bo'lishi shart (RSI 35..52 oralig'ida)
    3. Oxirgi shamcha tiklanish (impuls) ko'rsatishi shart (oxirgi yopilish oldingisidan baland)
    """
    if len(close_prices) < config.SLOW_EMA_PERIOD + 2:
        return False, {"reason": "Tarixiy ma'lumot yetarli emas"}

    fast_ema = calculate_ema(close_prices, config.FAST_EMA_PERIOD)
    slow_ema = calculate_ema(close_prices, config.SLOW_EMA_PERIOD)
    rsi = calculate_rsi(close_prices, config.RSI_PERIOD)
    current_price = close_prices[-1]
    prev_price = close_prices[-2]

    metrics = {
        "price": current_price,
        "fast_ema": fast_ema,
        "slow_ema": slow_ema,
        "rsi": rsi,
    }

    if fast_ema is None or slow_ema is None or rsi is None:
        return False, metrics

    trend_is_up = (fast_ema > slow_ema) and (current_price > slow_ema)
    rsi_in_pullback_zone = config.RSI_BUY_ZONE_LOW <= rsi <= config.RSI_BUY_ZONE_HIGH
    bullish_reversal_candle = current_price > prev_price

    should_enter = trend_is_up and rsi_in_pullback_zone and bullish_reversal_candle
    metrics["signal"] = should_enter
    return should_enter, metrics
