"""
24/7 VPS uchun yengil (Lightweight) Jonli Savdo Boti + Telegram Panel + Veb-Sayt Dashboard.
Standart Python kutubxonalarida ishlaydi (tashqi paketlar shart emas).
"""

import signal
import sys
import time
import config
from bot_context import BotContext, today_str
from market_data import fetch_klines, split_closed_candles
from strategy import evaluate_entry_signal
from telegram_controller import TelegramController, fmt_usd
from web_dashboard import start_web_dashboard


def symbols_to_fetch(ctx: BotContext) -> list[str]:
    """Tanlangan aktiv + ochiq bitimlar aktivlari (+ Avto-Skaner yoqilgan bo'lsa barcha aktivlar)."""
    with ctx.lock:
        symbols = [config.SYMBOL]
        symbols += [p.symbol for p in ctx.rm.open_positions]
        if config.AUTO_SCAN_MARKETS and not ctx.rm.open_positions:
            symbols += list(config.ALLOWED_SYMBOLS.keys())
    return list(dict.fromkeys(symbols))  # tartibni saqlagan holda takrorlarni olib tashlash


def refresh_market(ctx: BotContext) -> dict[str, dict]:
    """
    Har bir aktiv uchun shamchalarni yuklaydi. Signal faqat yopilgan shamchalar bo'yicha,
    SL/TP esa eng so'nggi (jonli) narx bo'yicha tekshiriladi.
    Bitta aktivda xato bo'lsa, qolganlari ishlashda davom etadi.
    """
    signals: dict[str, dict] = {}
    for sym in symbols_to_fetch(ctx):
        try:
            candles = fetch_klines(sym, config.TIMEFRAME, limit=config.KLINE_LIMIT + 1)
        except Exception as exc:  # noqa: BLE001
            print(f"[Xatolik] {sym} narxini olib bo'lmadi: {type(exc).__name__}: {exc}")
            continue
        closed, forming = split_closed_candles(candles)
        closed = closed[-config.KLINE_LIMIT:]
        if not closed:
            continue
        live_price = forming["close"] if forming else closed[-1]["close"]
        should_enter, metrics = evaluate_entry_signal([c["close"] for c in closed])
        with ctx.lock:
            ctx.update_market(sym, closed, live_price, metrics)
        signals[sym] = {"enter": should_enter, "candle_time": closed[-1]["open_time"], "price": live_price}
    return signals


def check_exits(ctx: BotContext, tg: TelegramController, now_str: str) -> None:
    """Ochiq bitimlarni har biri O'Z aktivining narxi bilan Stop-Loss / Take-Profit'ga tekshiradi."""
    messages = []
    with ctx.lock:
        for pos in list(ctx.rm.open_positions):
            price = ctx.price(pos.symbol)
            if price is None:
                continue  # narx eskirgan — taxmin bilan yopmaymiz
            if price <= pos.stop_loss_price:
                rec = ctx.rm.close_position_by_id(pos.position_id, price, "STOP-LOSS", now_str)
                messages.append(
                    f"🛑 *STOP-LOSS ISHLADI (Bitim #{pos.position_id} • {pos.symbol})*\n"
                    f"• Natija: `{rec['pnl_uzs']:+,.0f} so'm` (`{rec['pnl_usdt']:+.2f} USDT`, komissiya bilan)\n"
                    f"• Balans: `{rec['balance_after_uzs']:,.0f} so'm`"
                )
                if ctx.rm.kill_switch_active:
                    messages.append("🛑 *KILL-SWITCH YOQILDI:* kunlik 3% zarar limitiga yetildi. Bugun yangi bitim ochilmaydi.")
            elif price >= pos.take_profit_price:
                rec = ctx.rm.close_position_by_id(pos.position_id, price, "TAKE-PROFIT", now_str)
                messages.append(
                    f"🎯 *TAKE-PROFIT ISHLADI (Bitim #{pos.position_id} • {pos.symbol})*\n"
                    f"• Natija: `{rec['pnl_uzs']:+,.0f} so'm` (`{rec['pnl_usdt']:+.2f} USDT`, komissiya bilan)\n"
                    f"• Balans: `{rec['balance_after_uzs']:,.0f} so'm`"
                )
    for msg in messages:
        print(f"[{now_str}] {msg}")
        tg.send_message(msg)


def try_auto_entry(ctx: BotContext, tg: TelegramController, signals: dict[str, dict], now_str: str) -> None:
    msg = None
    with ctx.lock:
        allowed, _ = ctx.rm.can_open_trade(is_manual_add=False)
        if not allowed:
            return

        # Avto-Skaner o'chiq bo'lsa faqat tanlangan aktiv; yoqiq bo'lsa tanlangan aktiv birinchi tekshiriladi
        candidates = [config.SYMBOL]
        if config.AUTO_SCAN_MARKETS:
            candidates += [s for s in config.ALLOWED_SYMBOLS if s != config.SYMBOL]

        for sym in candidates:
            sig = signals.get(sym)
            if not sig or not sig["enter"]:
                continue
            # Bitta shamcha signali bo'yicha faqat bir marta kiriladi (aks holda Stop-Loss'dan
            # keyin 15 soniyada yana o'sha signalga kirib, zararni ko'paytirardi)
            if ctx.last_signal_candle.get(sym) == sig["candle_time"]:
                continue
            price = ctx.price(sym)
            if price is None:
                continue
            ctx.last_signal_candle[sym] = sig["candle_time"]
            config.SYMBOL = sym
            pos = ctx.rm.open_new_position(price, now_str, symbol=sym, source="AUTO")
            msg = (
                f"✅ *AVTOMATIK #{pos.position_id}-BITIM OCHILDI ({tg.mode_label()})*\n"
                f"• Bozor: `{pos.symbol}` ({config.ALLOWED_SYMBOLS.get(pos.symbol, '')})\n"
                f"• Kirish: `{fmt_usd(pos.entry_price)}` | Hajm: `${pos.position_value_usdt:.2f}`\n"
                f"• {tg.sl_label()}: `{fmt_usd(pos.stop_loss_price)}`\n"
                f"• {tg.tp_label()}: `{fmt_usd(pos.take_profit_price)}`"
            )
            print(f"[{now_str}] Bitim #{pos.position_id} ochildi ({pos.symbol}): {pos.entry_price}")
            break
    if msg:
        tg.send_message(msg)


def maybe_send_daily_report(ctx: BotContext, tg: TelegramController) -> None:
    now = config.local_now()
    today = today_str()
    if now.hour >= config.DAILY_REPORT_HOUR and ctx.last_report_date != today:
        ctx.last_report_date = today
        tg.send_message(tg.generate_daily_quant_review(ctx))


def run_bot_step(ctx: BotContext, tg: TelegramController) -> None:
    signals = refresh_market(ctx)
    now_str = config.local_now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Avval SL/TP — narx yangilangan zahoti himoya ishlashi kerak
    check_exits(ctx, tg, now_str)

    # 2. Telegram buyruqlari (/status, /add, /buy, /close, /report)
    updates = tg.fetch_updates()
    if updates:
        tg.handle_updates(updates, ctx, now_str)

    # 3. Kunlik hisobot (O'zbekiston vaqti bilan 20:00 dan keyin, kuniga bir marta)
    maybe_send_daily_report(ctx, tg)

    # 4. Avtomatik 1-bitimni ochish
    try_auto_entry(ctx, tg, signals, now_str)

    ctx.save_state()


def main() -> None:
    config.validate()
    if not config.PAPER_TRADING:
        print(
            "⛔ PAPER_TRADING=False, lekin real Binance buyurtma yuborish moduli hali yozilmagan.\n"
            "   Bot sizni chalg'itmasligi uchun ishga tushmaydi. PAPER_TRADING=True qiling."
        )
        sys.exit(1)

    print("🚀 Lightweight Quant Bot v3.1 (Telegram + Veb-Sayt Dashboard) ishga tushdi...")
    ctx = BotContext.load()
    print(
        f"   Balans: {ctx.rm.balance_usdt * config.UZS_PER_USD:,.0f} so'm | "
        f"Ochiq bitimlar: {len(ctx.rm.open_positions)} | Aktiv: {config.SYMBOL}"
    )
    tg = TelegramController()
    if not tg.is_configured:
        print("ℹ️ TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID o'rnatilmagan — Telegram o'chiq.")
    start_web_dashboard(ctx)

    def _graceful_exit(signum, _frame):
        print(f"\n⏹ To'xtatilmoqda (signal {signum}) — holat saqlanmoqda...")
        ctx.save_state()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _graceful_exit)
    signal.signal(signal.SIGINT, _graceful_exit)

    consecutive_errors = 0
    while True:
        started = time.time()
        try:
            run_bot_step(ctx, tg)
            consecutive_errors = 0
        except Exception as exc:  # noqa: BLE001
            consecutive_errors += 1
            print(f"[Xatolik] Bot qadamida kutilmagan xato: {type(exc).__name__}: {exc}")
            if consecutive_errors == 20:
                tg.send_message("⚠️ Bot ketma-ket 20 marta xatoga uchradi. Serverni tekshiring.")
        elapsed = time.time() - started
        time.sleep(max(1.0, config.CHECK_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
