# Lightweight Quant Trading Bot (1,000,000 UZS / ~$78 USDT)

Ushbu bot **Binance Spot** bozorida (`PAXGUSDT` — oltin yoki `BTCUSDT` — Bitcoin) qat'iy **1% Risk-Menejment** va **3% Kunlik Kill-Switch** qoidalari asosida ishlash uchun yaratilgan.

## VPS Resurs talablari (Edufayl Telegram botingiz yonida ishlashi uchun)
- **Operativ xotira (RAM):** ~15–20 MB (og'ir kutubxonalar yo'q, toza Python standart kutubxonalarida yozilgan).
- **Disk joyi:** < 50 KB (`bot_state.json` faqat oxirgi 20 ta bitim holatini saqlaydi, katta fayllar yig'maydi).
- **CPU:** < 1% (har 60 soniyada 1 marta yengil JSON so'rov yuboradi).

## Loyiha fayllari
- `config.py` — 1,000,000 so'm byudjet, 1% bitim xavfi, 1:2 foyda nisbati va 3% kunlik limit sozlamalari.
- `risk_manager.py` — Pozitsiya hajmini hisoblash, Stop-Loss / Take-Profit va kunlik Kill-Switch himoyasi.
- `strategy.py` — EMA 20/50 trend filtri va RSI 14 korreksiya (pullback) signali.
- `backtest.py` — 30 kunlik grafikda strategiyani pulsiz sinab ko'rish moduli.
- `bot.py` — 24/7 VPS `screen` sessiyasida ishlaydigan asosiy dastur.

## VPS'da `screen` orqali ishga tushirish

1. Fayllarni VPS serveringizga ko'chiring (masalan, `/root/trading-bot` papkasiga).
2. Avval tarixiy sinovni (Backtest) tekshirib ko'ring:
   ```bash
   python3 backtest.py
   ```
3. Edufayl botingizga xalaqit bermasdan yangi `screen` oching va botni ishga tushiring:
   ```bash
   screen -S trading_bot
   python3 bot.py
   ```
4. `screen`ni orqa fonga o'tkazish uchun: `Ctrl + A`, keyin `D` tugmasini bosing.
5. Qayta kirib ko'rish uchun:
   ```bash
   screen -r trading_bot
   ```
