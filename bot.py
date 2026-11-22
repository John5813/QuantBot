"""
24/7 VPS uchun yengil (Lightweight) Jonli Savdo Boti + Telegram Panel + Veb-Sayt Dashboard.
RAM sarfi: ~20 MB. CPU sarfi: < 1%.
Standart Python kutubxonalarida ishlaydi.
"""

import json
import time
import urllib.request
from datetime import datetime
import config
from risk_manager import RiskManager
from strategy import evaluate_entry_signal
from telegram_controller import TelegramController
from web_dashboard import BotWebContext, start_web_dashboard


def fetch_binance_klines(symbol: str, interval: str, limit: int = 100) -> list[dict]:
    """Binance Spot public API orqali oxirgi shamchalarni tortib oladi."""
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval={interval}&limit={limit}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "LightweightQuantBot/3.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    candles = []
    for item in raw:
        candles.append({
            "open_time": item[0],
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
        })
    return candles


def save_state(rm: RiskManager, path: str = "bot_state.json") -> None:
    data = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "PAPER_TRADING" if config.PAPER_TRADING else "LIVE",
        "selected_symbol": config.SYMBOL,
        "auto_scan_markets": config.AUTO_SCAN_MARKETS,
        "balance_usdt": rm.balance_usdt,
        "balance_uzs": round(rm.balance_usdt * config.UZS_PER_USD, 0),
        "free_capital_usdt": rm.free_capital_usdt,
        "daily_pnl_usdt": rm.daily_realized_pnl_usdt,
        "kill_switch_active": rm.kill_switch_active,
        "open_positions": [p.__dict__ for p in rm.open_positions],
        "recent_trades": rm.history[-20:],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_bot_step(
    rm: RiskManager,
    tg: TelegramController,
    web_ctx: BotWebContext,
    last_report_day: list[int],
) -> None:
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # Agar Avto-Skaner yoqilgan bo'lsa va ochiq bitim bo'lmasa, ruxsat berilgan 5 ta bozorni tekshiradi
    symbols_to_check = (
        list(config.ALLOWED_SYMBOLS.keys())
        if (config.AUTO_SCAN_MARKETS and len(rm.open_positions) == 0)
        else [config.SYMBOL]
    )

    should_enter = False
    metrics = {}
    candles = []
    current_price = web_ctx.current_price

    for sym in symbols_to_check:
        candles = fetch_binance_klines(sym, config.TIMEFRAME, limit=100)
        closes = [c["close"] for c in candles]
        current_price = closes[-1]
        should_enter, metrics = evaluate_entry_signal(closes)
        if should_enter:
            config.SYMBOL = sym
            break

    web_ctx.candles = candles
    web_ctx.current_price = current_price
    web_ctx.metrics = metrics

    # 1. Telegram buyruqlarini tekshirish (/status, /add, /buy, /close, /report)
    tg.poll_commands(rm, current_price, metrics, now_str)

    # 2. Har kuni soat 20:00 da Kunlik Matematik Spot Hisobotni yuborish
    if now.hour == config.DAILY_REPORT_HOUR and last_report_day[0] != now.day:
        last_report_day[0] = now.day
        daily_report = tg.generate_daily_quant_review(rm, current_price, metrics)
        tg.send_message(daily_report)

    # 3. Ochiq bitimlar (#1 va #2) uchun Stop-Loss va Take-Profit tekshirish
    for pos in list(rm.open_positions):
        if current_price <= pos.stop_loss_price:
            rec = rm.close_position_by_id(pos.position_id, current_price, "STOP-LOSS", now_str)
            msg = (
                f"🛑 *STOP-LOSS ISHLADI (Bitim #{pos.position_id} • {pos.symbol})*\n"
                f"• Zarar: `{rec['pnl_uzs']:,.0f} so'm` (`{rec['pnl_usdt']:+.2f} USDT`)\n"
                f"• Balans: `{rec['balance_after_uzs']:,.0f} so'm`"
            )
            print(f"[{now_str}] {msg}")
            tg.send_message(msg)
        elif current_price >= pos.take_profit_price:
            rec = rm.close_position_by_id(pos.position_id, current_price, "TAKE-PROFIT", now_str)
            msg = (
                f"🎯 *TAKE-PROFIT ISHLADI (Bitim #{pos.position_id} • {pos.symbol})*\n"
                f"• Foyda: `+{rec['pnl_uzs']:,.0f} so'm` (`{rec['pnl_usdt']:+.2f} USDT`)\n"
                f"• Balans: `{rec['balance_after_uzs']:,.0f} so'm`"
            )
            print(f"[{now_str}] {msg}")
            tg.send_message(msg)

    # 4. Avtomatik 1-bitimni ochish
    allowed, _ = rm.can_open_trade(is_manual_add=False)
    if not allowed:
        save_state(rm)
        return

    if should_enter:
        pos = rm.open_new_position(current_price, now_str, source="AUTO")
        msg = (
            f"✅ *AVTOMATIK #{pos.position_id}-BITIM OCHILDI ({'VIRTUAL' if config.PAPER_TRADING else 'LIVE'})*\n"
            f"• Bozor: `{pos.symbol}` ({config.ALLOWED_SYMBOLS.get(pos.symbol, '')})\n"
            f"• Kirish: `${pos.entry_price}`\n"
            f"• Stop-Loss (-1%): `${pos.stop_loss_price}`\n"
            f"• Take-Profit (+2%): `${pos.take_profit_price}`"
        )
        print(f"[{now_str}] Bitim #{pos.position_id} ochildi ({pos.symbol}): ${pos.entry_price}")
        tg.send_message(msg)

    save_state(rm)


def main() -> None:
    print("🚀 Lightweight Quant Bot v3.0 (Telegram + Veb-Sayt Dashboard) ishga tushdi...")
    rm = RiskManager()
    tg = TelegramController()
    web_ctx = BotWebContext(rm)
    start_web_dashboard(web_ctx)
    last_report_day = [0]

    while True:
        try:
            run_bot_step(rm, tg, web_ctx, last_report_day)
        except Exception as exc:
            print(f"[Xatolik] API ulanishda vaqtinchalik uzilish: {exc}")
        time.sleep(config.CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
