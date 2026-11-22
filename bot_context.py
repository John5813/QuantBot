"""
Bot sikli, Telegram va Veb-panel o'rtasidagi umumiy holat (shared state).

- Har bir aktivning narxi alohida saqlanadi: bitim faqat O'Z aktivining narxi bilan
  tekshiriladi va yopiladi (oldin BTC narxi bilan PAXG bitimi yopilib ketishi mumkin edi).
- Barcha o'zgartirishlar `lock` ostida bajariladi (veb-server alohida oqimda ishlaydi).
- Holat `bot_state.json` ga atomar yoziladi va qayta ishga tushganda tiklanadi.
"""

import json
import os
import time
from typing import Optional
import config
from risk_manager import RiskManager, TradePosition
from strategy import ema_series


class BotContext:
    def __init__(self, rm: RiskManager) -> None:
        self.rm = rm
        self.lock = rm.lock
        # symbol -> {"price", "updated_at", "candles", "metrics", "ema_fast", "ema_slow"}
        self.market: dict[str, dict] = {}
        # symbol -> signal bergan oxirgi yopilgan shamcha open_time (bir shamchada ikki marta kirmaslik uchun)
        self.last_signal_candle: dict[str, int] = {}
        self.last_report_date: Optional[str] = None
        self.started_at = time.time()

    # ------------------------------------------------------------------ bozor

    def update_market(self, symbol: str, closed: list[dict], live_price: float, metrics: dict) -> None:
        closes = [c["close"] for c in closed]
        fast = ema_series(closes, config.FAST_EMA_PERIOD)
        slow = ema_series(closes, config.SLOW_EMA_PERIOD)
        self.market[symbol] = {
            "price": live_price,
            "updated_at": time.time(),
            "candles": [
                {k: c[k] for k in ("open_time", "timestamp", "open", "high", "low", "close")}
                for c in closed[-60:]
            ],
            "ema_fast": [round(v, 6) if v is not None else None for v in fast[-60:]],
            "ema_slow": [round(v, 6) if v is not None else None for v in slow[-60:]],
            "metrics": metrics,
        }

    def price(self, symbol: str, max_age: float = config.MAX_PRICE_AGE_SECONDS) -> Optional[float]:
        """Faqat yangi (eskirmagan) narxni qaytaradi, aks holda None."""
        data = self.market.get(symbol)
        if not data or data.get("price", 0) <= 0:
            return None
        if time.time() - data["updated_at"] > max_age:
            return None
        return data["price"]

    def metrics(self, symbol: str) -> dict:
        return (self.market.get(symbol) or {}).get("metrics", {})

    # ------------------------------------------------------------------ qo'lda boshqaruv

    def open_manual(self, source: str, now_str: str) -> tuple[bool, str, Optional[TradePosition]]:
        with self.lock:
            symbol = config.SYMBOL
            price = self.price(symbol)
            if price is None:
                return False, f"{symbol} narxi hali yuklanmagan yoki eskirgan. Birozdan keyin urinib ko'ring.", None
            allowed, reason = self.rm.can_open_trade(is_manual_add=True)
            if not allowed:
                return False, reason, None
            try:
                pos = self.rm.open_new_position(price, now_str, symbol=symbol, source=source)
            except ValueError as exc:
                return False, str(exc), None
            return True, "Bitim ochildi", pos

    def close_one(self, position_id: int, reason: str, now_str: str) -> dict:
        with self.lock:
            pos = next((p for p in self.rm.open_positions if p.position_id == position_id), None)
            if pos is None:
                raise ValueError(f"#{position_id} raqamli ochiq bitim topilmadi.")
            price = self.price(pos.symbol)
            if price is None:
                raise ValueError(f"{pos.symbol} narxi eskirgan — bitimni hozir yopib bo'lmaydi.")
            return self.rm.close_position_by_id(position_id, price, reason, now_str)

    def close_all(self, reason: str, now_str: str) -> tuple[list[dict], list[str]]:
        records, errors = [], []
        with self.lock:
            for pid in [p.position_id for p in self.rm.open_positions]:
                try:
                    records.append(self.close_one(pid, reason, now_str))
                except ValueError as exc:
                    errors.append(str(exc))
        return records, errors

    def set_symbol(self, symbol: str) -> bool:
        if symbol not in config.ALLOWED_SYMBOLS:
            return False
        with self.lock:
            config.SYMBOL = symbol
            config.AUTO_SCAN_MARKETS = False
        return True

    # ------------------------------------------------------------------ ko'rinish

    def snapshot(self) -> dict:
        with self.lock:
            rm = self.rm
            sym = config.SYMBOL
            market = self.market.get(sym, {})
            prices = {s: d["price"] for s, d in self.market.items()}
            return {
                "mode": "PAPER_TRADING" if config.PAPER_TRADING else "LIVE",
                "symbol": sym,
                "timeframe": config.TIMEFRAME,
                "allowed_symbols": config.ALLOWED_SYMBOLS,
                "auto_scan_markets": config.AUTO_SCAN_MARKETS,
                "auto_trading_paused": rm.auto_trading_paused,
                "max_positions": config.MAX_CONCURRENT_POSITIONS,
                "stop_pct": config.STOP_LOSS_DISTANCE_PCT * 100,
                "tp_pct": config.STOP_LOSS_DISTANCE_PCT * config.REWARD_TO_RISK_RATIO * 100,
                "uzs_per_usd": config.UZS_PER_USD,
                "balance_usdt": round(rm.balance_usdt, 2),
                "balance_uzs": round(rm.balance_usdt * config.UZS_PER_USD, 0),
                "free_capital_usdt": rm.free_capital_usdt,
                "daily_pnl_usdt": round(rm.daily_realized_pnl_usdt, 4),
                "kill_switch_active": rm.kill_switch_active,
                "current_price": market.get("price", 0.0),
                "price_age_sec": round(time.time() - market["updated_at"], 1) if market else None,
                "prices": prices,
                "metrics": market.get("metrics", {}),
                "open_positions": [p.__dict__.copy() for p in rm.open_positions],
                "recent_trades": rm.history[-25:],
                "candles": market.get("candles", []),
                "ema_fast": market.get("ema_fast", []),
                "ema_slow": market.get("ema_slow", []),
            }

    # ------------------------------------------------------------------ saqlash

    def save_state(self, path: str = config.STATE_FILE) -> None:
        with self.lock:
            data = {
                "updated_at": config.local_now().isoformat(timespec="seconds"),
                "mode": "PAPER_TRADING" if config.PAPER_TRADING else "LIVE",
                "selected_symbol": config.SYMBOL,
                "auto_scan_markets": config.AUTO_SCAN_MARKETS,
                "last_signal_candle": self.last_signal_candle,
                "last_report_date": self.last_report_date,
                "balance_uzs": round(self.rm.balance_usdt * config.UZS_PER_USD, 0),
                "risk_manager": self.rm.to_state(),
            }
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp_path, path)  # yozish o'rtasida o'chib qolsa ham fayl buzilmaydi

    @classmethod
    def load(cls, path: str = config.STATE_FILE) -> "BotContext":
        if not os.path.exists(path):
            return cls(RiskManager())
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if "risk_manager" not in data:
            # Eski formatdagi fayl: faqat ko'rish uchun yozilgan edi, ishonchli tiklab bo'lmaydi
            print("[Holat] Eski formatdagi bot_state.json topildi — yangi holat bilan boshlanmoqda.")
            return cls(RiskManager())
        ctx = cls(RiskManager.from_state(data["risk_manager"]))
        sym = data.get("selected_symbol")
        if sym in config.ALLOWED_SYMBOLS:
            config.SYMBOL = sym
        config.AUTO_SCAN_MARKETS = bool(data.get("auto_scan_markets", config.AUTO_SCAN_MARKETS))
        ctx.last_signal_candle = {k: int(v) for k, v in (data.get("last_signal_candle") or {}).items()}
        ctx.last_report_date = data.get("last_report_date")
        return ctx


def today_str() -> str:
    return config.local_now().date().isoformat()

