"""
Risk-Menejment, Ko'p Bitimli (Multi-Position) Boshqaruv va Kill-Switch moduli.
Telegram/Veb orqali 1-bitim ustiga 2-bitimni qo'shishda ham 1% risk va 3% kunlik limitni qat'iy nazorat qiladi.

Barcha hisob-kitoblar Binance komissiyasini (kirish + chiqish) hisobga oladi:
Stop-Loss urilganda yo'qotiladigan summa (narx farqi + komissiyalar) balansning 1% idan oshmaydi.
"""

import threading
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from typing import List, Optional
import config


@dataclass
class TradePosition:
    position_id: int
    symbol: str
    source: str  # "AUTO", "TELEGRAM_MANUAL" yoki "WEB_MANUAL"
    entry_price: float
    quantity: float
    position_value_usdt: float
    stop_loss_price: float
    take_profit_price: float
    max_risk_usdt: float
    expected_reward_usdt: float
    opened_at: str
    entry_fee_usdt: float = 0.0


def _today() -> date:
    return config.local_now().date()


def _price_round(price: float) -> float:
    """Narxni aktivning kattaligiga qarab yaxlitlaydi (BTC ~ 2 xona, arzon tangalar ~ 6 xona)."""
    if price >= 1000:
        return round(price, 2)
    if price >= 1:
        return round(price, 4)
    return round(price, 8)


@dataclass
class RiskManager:
    balance_usdt: float = config.INITIAL_CAPITAL_USDT
    current_day: date = field(default_factory=_today)
    daily_start_balance_usdt: float = config.INITIAL_CAPITAL_USDT
    daily_realized_pnl_usdt: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    kill_switch_active: bool = False
    auto_trading_paused: bool = False
    next_position_id: int = 1
    open_positions: List[TradePosition] = field(default_factory=list)
    history: List[dict] = field(default_factory=list)
    # Bot sikli, Telegram va veb-server turli oqimlarda (thread) ishlaydi — umumiy qulf
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    # ------------------------------------------------------------------ hisob

    @property
    def used_capital_usdt(self) -> float:
        return round(sum(p.position_value_usdt for p in self.open_positions), 2)

    @property
    def free_capital_usdt(self) -> float:
        return round(max(0.0, self.balance_usdt - self.used_capital_usdt), 2)

    @property
    def total_open_risk_usdt(self) -> float:
        return round(sum(p.max_risk_usdt for p in self.open_positions), 2)

    @property
    def max_daily_loss_usdt(self) -> float:
        return self.daily_start_balance_usdt * config.MAX_DAILY_LOSS_PCT

    @staticmethod
    def risk_fraction_per_unit() -> float:
        """Pozitsiya qiymatining Stop-Loss'da yo'qoladigan ulushi (narx farqi + 2 ta komissiya)."""
        stop = config.STOP_LOSS_DISTANCE_PCT
        fee = config.TRADING_FEE_PCT
        return stop + fee + fee * (1.0 - stop)

    # ------------------------------------------------------------------ qoidalar

    def check_new_day(self, simulated_date: Optional[date] = None) -> None:
        today = simulated_date or _today()
        if today != self.current_day:
            self.current_day = today
            self.daily_start_balance_usdt = self.balance_usdt
            self.daily_realized_pnl_usdt = 0.0
            self.trades_today = 0
            self.kill_switch_active = False

    def can_open_trade(
        self,
        is_manual_add: bool = False,
        simulated_date: Optional[date] = None,
    ) -> tuple[bool, str]:
        """
        Avtomatik bot faqat 1 ta bitim ochadi.
        Foydalanuvchi Telegram/Veb orqali qo'lda bitim qo'shsa (`is_manual_add=True`),
        2-bitimga ham ruxsat beradi — lekin faqat kunlik 3% Kill-Switch buzilmasa!
        """
        self.check_new_day(simulated_date)

        if self.kill_switch_active or self.daily_realized_pnl_usdt <= -self.max_daily_loss_usdt:
            self.kill_switch_active = True
            return (
                False,
                f"🛑 KILL-SWITCH AKTIV: Kunlik 3% zarar limitiga yetdi "
                f"({self.daily_realized_pnl_usdt:.2f} USDT / "
                f"{self.daily_realized_pnl_usdt * config.UZS_PER_USD:,.0f} so'm). "
                f"Bugun yangi bitim ochish bloklangan!",
            )

        if not is_manual_add and self.auto_trading_paused:
            return False, "Avtomatik savdo vaqtincha pauza qilingan."

        if not is_manual_add and len(self.open_positions) >= 1:
            return False, "1-bitim ishlamoqda (2-bitimni faqat qo'lda /add buyrug'i bilan qo'shish mumkin)."

        if len(self.open_positions) >= config.MAX_CONCURRENT_POSITIONS:
            return (
                False,
                f"Maksimal {config.MAX_CONCURRENT_POSITIONS} ta parallel bitim ochilgan. "
                f"Spot balans himoyasi uchun yangi bitimga ruxsat berilmaydi.",
            )

        next_trade_risk = self.balance_usdt * config.RISK_PER_TRADE_PCT
        worst_case_daily_loss = abs(min(0.0, self.daily_realized_pnl_usdt)) + self.total_open_risk_usdt + next_trade_risk
        # 0.5% tolerantlik — faqat narx yaxlitlashdagi mayda farqlar uchun
        if worst_case_daily_loss > self.max_daily_loss_usdt * 1.005:
            return (
                False,
                "Xavfsizlik cheklovi: barcha ochiq bitimlar Stop-Loss'ga tushsa, kunlik 3% limit buziladi.",
            )

        if self._target_position_value() < config.MIN_ORDER_USDT:
            return False, f"Bo'sh mablag' yetarli emas (Binance minimal buyurtmasi ${config.MIN_ORDER_USDT:.0f})."

        return True, "Ruxsat berildi"

    def _target_position_value(self) -> float:
        max_risk_usdt = self.balance_usdt * config.RISK_PER_TRADE_PCT
        return min(
            max_risk_usdt / self.risk_fraction_per_unit(),
            self.balance_usdt * config.MAX_POSITION_CAPITAL_PCT,
            self.free_capital_usdt,
        )

    # ------------------------------------------------------------------ bitimlar

    def open_new_position(
        self,
        entry_price: float,
        timestamp: str,
        symbol: str,
        source: str = "AUTO",
    ) -> TradePosition:
        """1% umumiy balans xavfi asosida yangi (1- yoki 2-) bitimni ochadi."""
        if entry_price <= 0:
            raise ValueError("Kirish narxi noto'g'ri (narx hali yuklanmagan).")
        if symbol not in config.ALLOWED_SYMBOLS:
            raise ValueError(f"{symbol} ruxsat etilgan aktivlar ro'yxatida yo'q.")

        target_value_usdt = self._target_position_value()
        if target_value_usdt < config.MIN_ORDER_USDT:
            raise ValueError("Bo'sh mablag' minimal buyurtma hajmidan kam.")

        stop_distance_pct = config.STOP_LOSS_DISTANCE_PCT
        quantity = target_value_usdt / entry_price
        stop_loss_price = _price_round(entry_price * (1.0 - stop_distance_pct))
        take_profit_price = _price_round(entry_price * (1.0 + stop_distance_pct * config.REWARD_TO_RISK_RATIO))

        entry_fee = target_value_usdt * config.TRADING_FEE_PCT
        risk_usdt = (entry_price - stop_loss_price) * quantity + entry_fee + stop_loss_price * quantity * config.TRADING_FEE_PCT
        reward_usdt = (take_profit_price - entry_price) * quantity - entry_fee - take_profit_price * quantity * config.TRADING_FEE_PCT

        pos = TradePosition(
            position_id=self.next_position_id,
            symbol=symbol,
            source=source,
            entry_price=entry_price,
            quantity=quantity,
            position_value_usdt=round(target_value_usdt, 2),
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            max_risk_usdt=round(risk_usdt, 4),
            expected_reward_usdt=round(reward_usdt, 4),
            opened_at=timestamp,
            entry_fee_usdt=round(entry_fee, 6),
        )
        self.next_position_id += 1
        self.open_positions.append(pos)
        return pos

    def close_position_by_id(
        self,
        position_id: int,
        exit_price: float,
        reason: str,
        closed_at: str,
    ) -> dict:
        if exit_price <= 0:
            raise ValueError("Chiqish narxi noto'g'ri (narx hali yuklanmagan).")

        target_idx = next(
            (idx for idx, p in enumerate(self.open_positions) if p.position_id == position_id),
            None,
        )
        if target_idx is None:
            raise ValueError(f"#{position_id} raqamli ochiq bitim topilmadi.")

        pos = self.open_positions.pop(target_idx)
        exit_fee = exit_price * pos.quantity * config.TRADING_FEE_PCT
        fees_usdt = pos.entry_fee_usdt + exit_fee
        pnl_usdt = (exit_price - pos.entry_price) * pos.quantity - fees_usdt
        pnl_uzs = pnl_usdt * config.UZS_PER_USD

        # Balansni yaxlitlamasdan saqlaymiz — aks holda ko'p bitimdan keyin xatolik yig'iladi
        self.balance_usdt += pnl_usdt
        self.daily_realized_pnl_usdt += pnl_usdt
        self.trades_today += 1

        if pnl_usdt < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if self.daily_realized_pnl_usdt <= -self.max_daily_loss_usdt:
            self.kill_switch_active = True

        record = {
            "position_id": pos.position_id,
            "symbol": pos.symbol,
            "source": pos.source,
            "opened_at": pos.opened_at,
            "closed_at": closed_at,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "quantity": pos.quantity,
            "fees_usdt": round(fees_usdt, 4),
            "pnl_usdt": round(pnl_usdt, 4),
            "pnl_uzs": round(pnl_uzs, 0),
            "reason": reason,
            "balance_after_usdt": round(self.balance_usdt, 4),
            "balance_after_uzs": round(self.balance_usdt * config.UZS_PER_USD, 0),
        }
        self.history.append(record)
        if len(self.history) > config.MAX_HISTORY_IN_MEMORY:
            del self.history[: len(self.history) - config.MAX_HISTORY_IN_MEMORY]
        return record

    # ------------------------------------------------------------------ saqlash / tiklash

    def to_state(self) -> dict:
        return {
            "balance_usdt": self.balance_usdt,
            "current_day": self.current_day.isoformat(),
            "daily_start_balance_usdt": self.daily_start_balance_usdt,
            "daily_realized_pnl_usdt": self.daily_realized_pnl_usdt,
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "kill_switch_active": self.kill_switch_active,
            "auto_trading_paused": self.auto_trading_paused,
            "next_position_id": self.next_position_id,
            "open_positions": [asdict(p) for p in self.open_positions],
            "history": self.history[-config.MAX_HISTORY_IN_MEMORY:],
        }

    @classmethod
    def from_state(cls, data: dict) -> "RiskManager":
        rm = cls()
        rm.balance_usdt = float(data.get("balance_usdt", rm.balance_usdt))
        if data.get("current_day"):
            rm.current_day = date.fromisoformat(data["current_day"])
        rm.daily_start_balance_usdt = float(data.get("daily_start_balance_usdt", rm.balance_usdt))
        rm.daily_realized_pnl_usdt = float(data.get("daily_realized_pnl_usdt", 0.0))
        rm.trades_today = int(data.get("trades_today", 0))
        rm.consecutive_losses = int(data.get("consecutive_losses", 0))
        rm.kill_switch_active = bool(data.get("kill_switch_active", False))
        rm.auto_trading_paused = bool(data.get("auto_trading_paused", False))
        known = {f.name for f in fields(TradePosition)}
        rm.open_positions = [
            TradePosition(**{k: v for k, v in p.items() if k in known})
            for p in data.get("open_positions", [])
        ]
        rm.history = list(data.get("history", []))
        max_id = max([p.position_id for p in rm.open_positions] + [h.get("position_id", 0) for h in rm.history] + [0])
        rm.next_position_id = max(int(data.get("next_position_id", 1)), max_id + 1)
        return rm
