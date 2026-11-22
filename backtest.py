"""
Tarixiy sinov (Backtest) moduli.
Binance'da pul yoki API kalit bo'lmasa ham, Binance'ning ochiq tarixiy shamchalarini yuklab oladi
(internet bo'lmasa — oflayn simulyatsiya) va 1,000,000 so'm bilan strategiyani sinaydi.

Jonli bot bilan bir xil qoidalar ishlatiladi:
- signal faqat yopilgan shamchada, KLINE_LIMIT ta oxirgi shamcha bo'yicha;
- Binance komissiyasi (kirish + chiqish) hisobga olinadi;
- bitta shamchada ham SL, ham TP urilgan bo'lsa — ehtiyotkorlik bilan SL deb hisoblanadi;
- narx SL dan pastda ochilsa (gap), bitim SL da emas, ochilish narxida yopiladi.

Ishlatish:  python3 backtest.py [SYMBOL] [KUNLAR]   (masalan: python3 backtest.py BTCUSDT 30)
"""

import math
import random
import sys
from datetime import date, timedelta
import config
from market_data import fetch_history
from risk_manager import RiskManager
from strategy import evaluate_entry_signal


def generate_fallback_candles(days: int = 15, start_price: float = 2650.0) -> list[dict]:
    """Internet bo'lmaganda strategiya kodini tekshirish uchun sun'iy (tasodifiy) shamchalar."""
    rng = random.Random(42)
    candles = []
    price = start_price
    start_date = date.today() - timedelta(days=days)
    total_candles = days * 24 * 4
    for i in range(total_candles):
        current_day = start_date + timedelta(days=i // 96)
        wave = math.sin(i / 45.0) * 1.8 + math.sin(i / 180.0) * 2.5
        noise = rng.gauss(0.05, 3.2)
        open_p = price
        close_p = max(start_price * 0.5, round(open_p + wave * 0.25 + noise, 2))
        high_p = round(max(open_p, close_p) + abs(rng.gauss(0, 2.5)), 2)
        low_p = round(min(open_p, close_p) - abs(rng.gauss(0, 2.5)), 2)
        price = close_p
        candles.append({
            "open_time": i,
            "date": current_day,
            "timestamp": f"{current_day.isoformat()} {(i % 96) // 4:02d}:{((i % 96) % 4) * 15:02d}",
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
        })
    return candles


def run_backtest(symbol: str = config.SYMBOL, days: int = 30) -> dict:
    try:
        print(f"⏳ Binance'dan {symbol} ning oxirgi {days} kunlik {config.TIMEFRAME} shamchalari yuklanmoqda...")
        candles = fetch_history(symbol, config.TIMEFRAME, days)
        if len(candles) < config.SLOW_EMA_PERIOD + 2:
            raise RuntimeError("shamchalar yetarli emas")
        source_label = "BINANCE REAL TARIXIY MA'LUMOTLARI"
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Binance'ga ulanib bo'lmadi ({type(exc).__name__}: {exc}). Oflayn simulyatsiya ishlatiladi.")
        candles = generate_fallback_candles(days=min(days, 15))
        source_label = "OFLAYN SIMULYATSIYA (TASODIFIY, REAL EMAS!)"

    rm = RiskManager(current_day=candles[0]["date"])
    closes: list[float] = []
    kill_switch_triggers = 0
    peak_balance = rm.balance_usdt
    max_drawdown_pct = 0.0
    total_fees = 0.0

    for c in candles:
        rm.check_new_day(c["date"])

        # 1. Avval ochiq bitimlar shu shamcha ichida SL/TP ga tegdimi — tekshiramiz
        for pos in list(rm.open_positions):
            was_active = rm.kill_switch_active
            if c["low"] <= pos.stop_loss_price:
                fill = min(c["open"], pos.stop_loss_price)  # gap pastga bo'lsa, yomonroq narxda chiqiladi
                rec = rm.close_position_by_id(pos.position_id, fill, "STOP-LOSS", c["timestamp"])
            elif c["high"] >= pos.take_profit_price:
                fill = max(c["open"], pos.take_profit_price)
                rec = rm.close_position_by_id(pos.position_id, fill, "TAKE-PROFIT", c["timestamp"])
            else:
                continue
            total_fees += rec["fees_usdt"]
            if not was_active and rm.kill_switch_active:
                kill_switch_triggers += 1

        peak_balance = max(peak_balance, rm.balance_usdt)
        max_drawdown_pct = max(max_drawdown_pct, (peak_balance - rm.balance_usdt) / peak_balance * 100)

        # 2. Shamcha yopildi — signalni tekshiramiz va yopilish narxida kiramiz
        closes.append(c["close"])
        allowed, _ = rm.can_open_trade(is_manual_add=False, simulated_date=c["date"])
        if not allowed:
            continue
        should_enter, _ = evaluate_entry_signal(closes[-config.KLINE_LIMIT:])
        if should_enter:
            rm.open_new_position(c["close"], c["timestamp"], symbol=symbol, source="AUTO")

    # Oxirida ochiq qolgan bitimni oxirgi narxda yopamiz — aks holda natija to'liq bo'lmaydi
    for pos in list(rm.open_positions):
        rec = rm.close_position_by_id(pos.position_id, candles[-1]["close"], "BACKTEST-END", candles[-1]["timestamp"])
        total_fees += rec["fees_usdt"]

    total_trades = len(rm.history)
    wins = [t for t in rm.history if t["pnl_usdt"] > 0]
    losses = [t for t in rm.history if t["pnl_usdt"] <= 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0
    gross_win = sum(t["pnl_usdt"] for t in wins)
    gross_loss = -sum(t["pnl_usdt"] for t in losses)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    net_profit_usdt = rm.balance_usdt - config.INITIAL_CAPITAL_USDT
    net_profit_uzs = net_profit_usdt * config.UZS_PER_USD
    # 1:2 nisbat va komissiya bilan zararsizlik nuqtasi (break-even) g'alaba ulushi
    risk_frac = RiskManager.risk_fraction_per_unit()
    reward_frac = config.STOP_LOSS_DISTANCE_PCT * config.REWARD_TO_RISK_RATIO - 2 * config.TRADING_FEE_PCT
    breakeven_wr = risk_frac / (risk_frac + reward_frac) * 100

    print("=" * 72)
    print(f"📊 BACKTEST NATIJASI ({symbol} | {source_label})")
    print(f"   Davr: {candles[0]['timestamp']} — {candles[-1]['timestamp']} ({len(candles)} ta shamcha)")
    print("=" * 72)
    print(f"Boshlang'ich kapital : {config.INITIAL_CAPITAL_UZS:,.0f} so'm (${config.INITIAL_CAPITAL_USDT:.2f} USDT)")
    print(f"Yakuniy balans       : {rm.balance_usdt * config.UZS_PER_USD:,.0f} so'm (${rm.balance_usdt:.2f} USDT)")
    print(f"Sof foyda / zarar    : {net_profit_uzs:+,.0f} so'm ({net_profit_usdt:+.2f} USDT)")
    print(f"To'langan komissiya  : {total_fees * config.UZS_PER_USD:,.0f} so'm (${total_fees:.2f})")
    print(f"Jami bitimlar soni   : {total_trades} ta (Yutuq: {len(wins)} ta | Zarar: {len(losses)} ta)")
    print(f"G'alaba ulushi       : {win_rate:.1f}% (komissiya bilan zararsizlik chegarasi ~{breakeven_wr:.1f}%)")
    print(f"Profit Factor        : {profit_factor:.2f}")
    print(f"Maksimal pasayish    : {max_drawdown_pct:.2f}%")
    print(f"Kill-Switch ishlashi : {kill_switch_triggers} marta (kunlik 3% limitdan himoya qildi)")
    if total_trades < 30:
        print("⚠️ Bitimlar soni 30 tadan kam — natija statistik jihatdan ishonchli emas.")
    print("=" * 72)

    return {
        "trades": total_trades,
        "win_rate": win_rate,
        "net_profit_usdt": net_profit_usdt,
        "max_drawdown_pct": max_drawdown_pct,
        "final_balance_usdt": rm.balance_usdt,
    }


if __name__ == "__main__":
    sym = sys.argv[1].upper() if len(sys.argv) > 1 else config.SYMBOL
    if sym not in config.ALLOWED_SYMBOLS:
        sys.exit(f"{sym} ruxsat etilgan aktivlar ro'yxatida yo'q: {', '.join(config.ALLOWED_SYMBOLS)}")
    period_days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    run_backtest(sym, period_days)
