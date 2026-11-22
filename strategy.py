"""
Yengil (Lightweight) Algoritmik Strategiya Moduli.
VPS xotirasini tejash uchun og'ir kutubxonalarsiz (pure Python) yozilgan (~15 MB RAM).
"""

from typing import List, Optional
import config


def calculate_ema(prices: List[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return round(ema, 4)


def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
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
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def evaluate_entry_signal(close_prices: List[float]) -> tuple[bool, dict]:
    """
    Qat'iy 3 bosqichli filtr:
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
    return should_enter, metrics
