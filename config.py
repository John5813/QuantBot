"""
1,000,000 UZS (~$78.12 USDT) uchun qat'iy Risk-Menejment, Veb-Sayt Paneli va Telegram sozlamalari.
"""

import os

# 1. REJIM: True bo'lsa virtual hamyonda (pulsiz) sinaydi, False bo'lsa real Binance'da ishlaydi
PAPER_TRADING = True

# 2. BOZOR TANLASH TIZIMI (Foydalanuvchi Veb-sayt yoki Telegram orqali o'zgartira oladi)
# Ruxsat berilgan eng ishonchli Spot aktivlar ro'yxati:
ALLOWED_SYMBOLS = {
    "PAXGUSDT": "Oltin (PAXG/USDT)",
    "BTCUSDT": "Bitcoin (BTC/USDT)",
    "ETHUSDT": "Ethereum (ETH/USDT)",
    "BNBUSDT": "Binance Coin (BNB/USDT)",
    "SOLUSDT": "Solana (SOL/USDT)",
}

# Boshlang'ich tanlangan aktiv:
SYMBOL = "PAXGUSDT"

# AUTO_SCAN_MARKETS = False bo'lsa: Bot FAQAT siz tanlagan bitta aktivda (masalan, Oltinda) ishlaydi.
# AUTO_SCAN_MARKETS = True bo'lsa: Bot yuqoridagi 5 ta ishonchli aktivni skaner qilib, qaysi birida signal chiqsa o'shanga kiradi.
AUTO_SCAN_MARKETS = False

TIMEFRAME = "15m"
CHECK_INTERVAL_SECONDS = 15

# 3. VEB-SAYT (WEB DASHBOARD) SOZLAMALARI
WEB_HOST = "0.0.0.0"
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

# 4. KAPITAL VA VALYUTA KURS SOZLAMALARI
UZS_PER_USD = 12800.0
INITIAL_CAPITAL_UZS = 1_000_000.0
INITIAL_CAPITAL_USDT = round(INITIAL_CAPITAL_UZS / UZS_PER_USD, 2)  # ~$78.12 USDT

# 5. TEMIR RISK-MENEJMENT VA KO'P BITIMLI (MULTI-POSITION) QOIDALAR
RISK_PER_TRADE_PCT = 0.01        # Har bir bitimda umumiy balansning maksimum 1% i xavf ostida (~10,000 so'm)
REWARD_TO_RISK_RATIO = 2.0       # Foyda xatardan kamida 2 barobar ko'p bo'lishi shart (1:2)
MAX_DAILY_LOSS_PCT = 0.03        # Kunlik maksimal zarar 3% (~30,000 so'm). Bunga yetsa Kill-Switch ishlaydi!
MAX_CONCURRENT_POSITIONS = 2     # Bir vaqtning o'zida maksimum 2 ta bitim
MAX_POSITION_CAPITAL_PCT = 0.48  # Har bir Spot bitimga balansning 48% i (~480,000 so'm) kiradi
STOP_LOSS_DISTANCE_PCT = 0.0208  # 48% balans bilan kirganda -2.08% narx tushishi = umumiy balansning -1% zarari

# 6. STRATEGIYA PARAMETRLARI (Trend + Impuls)
FAST_EMA_PERIOD = 20
SLOW_EMA_PERIOD = 50
RSI_PERIOD = 14
RSI_BUY_ZONE_LOW = 35.0
RSI_BUY_ZONE_HIGH = 52.0

# 7. KUNLIK HISOBOT VAQTI
DAILY_REPORT_HOUR = 20

# 8. API KALITLAR
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
