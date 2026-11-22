"""
Risk-Menejment, Ko'p Bitimli (Multi-Position) Boshqaruv va Kill-Switch moduli.
Telegram orqali 1-bitim ustiga 2-bitimni qo'shishda ham 1% risk va 3% kunlik limitni qat'iy nazorat qiladi.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional
import config


@dataclass
class TradePosition:
    position_id: int
    symbol: str
    source: str  # "AUTO" yoki "TELEGRAM_MANUAL"
    entry_price: float
    quantity: float
    position_value_usdt: float
    stop_loss_price: float
    take_profit_price: float
    max_risk_usdt: float
    expected_reward_usdt: float
    opened_at: str


@dataclass
class RiskManager:
    balance_usdt: float = config.INITIAL_CAPITAL_USDT
    current_day: date = field(default_factory=date.today)
    daily_start_balance_usdt: float = config.INITIAL_CAPITAL_USDT
    daily_realized_pnl_usdt: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    kill_switch_active: bool = False
    auto_trading_paused: bool = False
    next_position_id: int = 1
    open_positions: List[TradePosition] = field(default_factory=list)
    history: List[dict] = field(default_factory=list)

    @property
    def used_capital_usdt(self) -> float:
        return round(sum(p.position_value_usdt for p in self.open_positions), 2)

    @property
    def free_capital_usdt(self) -> float:
        return round(max(0.0, self.balance_usdt - self.used_capital_usdt), 2)

    @property
    def total_open_risk_usdt(self) -> float:
        return round(sum(p.max_risk_usdt for p in self.open_positions), 2)

    def check_new_day(self, simulated_date: Optional[date] = None) -> None:
        today = simulated_date or date.today()
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
        Avtomatik bot odatda 1 ta bitim ochadi.
        Foydalanuvchi Telegram orqali '/add' yoki '/buy' bersa (`is_manual_add=True`),
        2-bitimni ham qo'shishga ruxsat beradi — lekin faqat kunlik 3% Kill-Switch buzilmasa!
        """
        self.check_new_day(simulated_date)

        max_daily_loss_usdt = self.daily_start_balance_usdt * config.MAX_DAILY_LOSS_PCT
        if self.daily_realized_pnl_usdt <= -max_daily_loss_usdt:
            self.kill_switch_active = True
            return (
                False,
                f"🛑 KILL-SWITCH AKTIV: Kunlik 3% zarar limitiga yetdi "
                f"({self.daily_realized_pnl_usdt:.2f} USDT / "
                f"{self.daily_realized_pnl_usdt * config.UZS_PER_USD:,.0f} so'm). "
                f"Bugun yangi bitim ochish bloklangan!",
            )

        if not is_manual_add and self.auto_trading_paused:
            return False, "Avtomatik savdo Telegram orqali vaqtincha pauza qilingan."

        # Avtomatik rejimda faqat 1 ta bitim, Telegram buyrug'i bilan 2 tagacha bitim
        if not is_manual_add and len(self.open_positions) >= 1:
            return False, "1-bitim ishlamoqda (2-bitimni Telegram orqali /add buyrug'i bilan qo'shish mumkin)."

        if len(self.open_positions) >= config.MAX_CONCURRENT_POSITIONS:
            return (
                False,
                f"Maksimal {config.MAX_CONCURRENT_POSITIONS} ta parallel bitim ochilgan. "
                f"Spot balans himoyasi uchun 3-bitimga ruxsat berilmaydi.",
            )

        # Agar 2-bitim ochilsa va ikkalasi ham Stop-Lossga tushsa, kunlik 3% limitdan oshib ketmasligini tekshirish
        next_trade_risk = self.balance_usdt * config.RISK_PER_TRADE_PCT
        worst_case_daily_loss = abs(min(0.0, self.daily_realized_pnl_usdt)) + self.total_open_risk_usdt + next_trade_risk
        if worst_case_daily_loss > max_daily_loss_usdt * 1.05:
            return (
                False,
                "Xavfsizlik cheklovi: 2-bitimni qo'shish kunlik 3% maksimal xavf chegarasidan oshib ketadi.",
            )

        return True, "Ruxsat berildi"

    def open_new_position(
        self,
        entry_price: float,
        timestamp: str,
        source: str = "AUTO",
    ) -> TradePosition:
        """
        1% umumiy balans xavfi asosida yangi (1- yoki 2-) bitimni ochadi.
        """
        max_risk_usdt = self.balance_usdt * config.RISK_PER_TRADE_PCT
        stop_distance_pct = config.STOP_LOSS_DISTANCE_PCT

        target_value_usdt = min(
            max_risk_usdt / stop_distance_pct,
            self.balance_usdt * config.MAX_POSITION_CAPITAL_PCT,
            self.free_capital_usdt,
        )
        quantity = target_value_usdt / entry_price

        stop_loss_price = round(entry_price * (1.0 - stop_distance_pct), 4)
        take_profit_distance_pct = stop_distance_pct * config.REWARD_TO_RISK_RATIO
        take_profit_price = round(entry_price * (1.0 + take_profit_distance_pct), 4)
        actual_risk_usdt = round(target_value_usdt * stop_distance_pct, 2)
        expected_reward_usdt = round(actual_risk_usdt * config.REWARD_TO_RISK_RATIO, 2)

        pos = TradePosition(
            position_id=self.next_position_id,
            symbol=config.SYMBOL,
            source=source,
            entry_price=entry_price,
            quantity=round(quantity, 6),
            position_value_usdt=round(target_value_usdt, 2),
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            max_risk_usdt=actual_risk_usdt,
            expected_reward_usdt=expected_reward_usdt,
            opened_at=timestamp,
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
        target_idx = None
        for idx, p in enumerate(self.open_positions):
            if p.position_id == position_id:
                target_idx = idx
                break

        if target_idx is None:
            raise ValueError(f"#{position_id} raqamli ochiq bitim topilmadi.")

        pos = self.open_positions.pop(target_idx)
        pnl_usdt = (exit_price - pos.entry_price) * pos.quantity
        pnl_uzs = pnl_usdt * config.UZS_PER_USD

        self.balance_usdt = round(self.balance_usdt + pnl_usdt, 2)
        self.daily_realized_pnl_usdt = round(self.daily_realized_pnl_usdt + pnl_usdt, 2)
        self.trades_today += 1

        if pnl_usdt < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if self.daily_realized_pnl_usdt <= -(self.daily_start_balance_usdt * config.MAX_DAILY_LOSS_PCT):
            self.kill_switch_active = True

        record = {
            "position_id": pos.position_id,
            "symbol": pos.symbol,
            "source": pos.source,
            "opened_at": pos.opened_at,
            "closed_at": closed_at,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "pnl_usdt": round(pnl_usdt, 2),
            "pnl_uzs": round(pnl_uzs, 0),
            "reason": reason,
            "balance_after_usdt": self.balance_usdt,
            "balance_after_uzs": round(self.balance_usdt * config.UZS_PER_USD, 0),
        }
        self.history.append(record)
        return record
