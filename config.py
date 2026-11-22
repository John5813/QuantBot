"""
1,000,000 UZS (~$78 USDT) uchun qat'iy Risk-Menejment, Veb-Sayt Paneli va Telegram sozlamalari.

Mahfiy qiymatlar (tokenlar, kalitlar) kodga yozilmaydi — ular `.env` faylidan yoki
muhit o'zgaruvchilaridan (environment variables) o'qiladi. Namuna: `.env.example`.
"""

import os
from datetime import datetime, timedelta, timezone


def _load_dotenv(path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")) -> None:
    """Tashqi kutubxonasiz oddiy `.env` o'quvchi (KEY=VALUE qatorlari)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Haqiqiy muhit o'zgaruvchilari .env dan ustun turadi
            os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


_load_dotenv()

# 1. REJIM: True bo'lsa virtual hamyonda (pulsiz) sinaydi.
# DIQQAT: Real Binance buyurtma (order) yuborish hali YOZILMAGAN. False qilinsa bot
# ishga tushmaydi — aks holda "LIVE" deb yozib, aslida virtual savdo qilib, sizni chalg'itardi.
PAPER_TRADING = _env_bool("PAPER_TRADING", True)

# 2. BOZOR TANLASH TIZIMI (Foydalanuvchi Veb-sayt orqali o'zgartira oladi)
ALLOWED_SYMBOLS = {
    "PAXGUSDT": "Oltin (PAXG/USDT)",
    "BTCUSDT": "Bitcoin (BTC/USDT)",
    "ETHUSDT": "Ethereum (ETH/USDT)",
    "BNBUSDT": "Binance Coin (BNB/USDT)",
    "SOLUSDT": "Solana (SOL/USDT)",
}

# Boshlang'ich tanlangan aktiv (bot_state.json dagi saqlangan tanlov ustun turadi):
SYMBOL = "PAXGUSDT"

# AUTO_SCAN_MARKETS = False: Bot FAQAT tanlangan bitta aktivda ishlaydi.
# AUTO_SCAN_MARKETS = True: ochiq bitim bo'lmaganda 5 ta aktivni skaner qilib, signal chiqqaniga kiradi.
AUTO_SCAN_MARKETS = False

TIMEFRAME = "15m"
CHECK_INTERVAL_SECONDS = 15
# Indikatorlar uchun nechta YOPILGAN shamcha ishlatiladi (jonli bot va backtest bir xil bo'lishi shart)
KLINE_LIMIT = 200
# Narx shu soniyadan eski bo'lsa, qo'lda bitim ochish rad etiladi
MAX_PRICE_AGE_SECONDS = 120

# 3. VEB-SAYT (WEB DASHBOARD) SOZLAMALARI
# Xavfsizlik: standart holatda faqat serverning o'zidan (127.0.0.1) ochiladi.
# Tashqaridan ochish uchun WEB_HOST=0.0.0.0 VA albatta WEB_DASHBOARD_TOKEN o'rnating.
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_DASHBOARD_TOKEN = os.getenv("WEB_DASHBOARD_TOKEN", "")

# 4. KAPITAL VA VALYUTA KURS SOZLAMALARI
UZS_PER_USD = float(os.getenv("UZS_PER_USD", "12800"))
INITIAL_CAPITAL_UZS = 1_000_000.0
# Yaxlitlanmaydi — aks holda so'mdagi hisob boshidanoq siljib ketadi (~$78.125 USDT)
INITIAL_CAPITAL_USDT = INITIAL_CAPITAL_UZS / UZS_PER_USD

# 5. TEMIR RISK-MENEJMENT VA KO'P BITIMLI (MULTI-POSITION) QOIDALAR
RISK_PER_TRADE_PCT = 0.01        # Har bir bitimda balansning maksimum 1% i xavf ostida (komissiya bilan birga)
REWARD_TO_RISK_RATIO = 2.0       # Narx bo'yicha foyda masofasi = 2 x stop masofasi (1:2)
MAX_DAILY_LOSS_PCT = 0.03        # Kunlik maksimal zarar 3%. Bunga yetsa Kill-Switch ishlaydi!
MAX_CONCURRENT_POSITIONS = 2     # Bir vaqtning o'zida maksimum 2 ta bitim
MAX_POSITION_CAPITAL_PCT = 0.48  # Bitta bitimga balansning ko'pi bilan 48% i kiradi
STOP_LOSS_DISTANCE_PCT = 0.0208  # Stop-Loss kirish narxidan -2.08% pastda (Take-Profit +4.16% tepada)
TRADING_FEE_PCT = 0.001          # Binance Spot komissiyasi: har bir tomon (kirish/chiqish) uchun 0.1%
MIN_ORDER_USDT = 5.0             # Binance Spot minimal buyurtma hajmi (~$5)
MAX_HISTORY_IN_MEMORY = 500      # Xotirada saqlanadigan yopilgan bitimlar soni

# 6. STRATEGIYA PARAMETRLARI (Trend + Impuls)
FAST_EMA_PERIOD = 20
SLOW_EMA_PERIOD = 50
RSI_PERIOD = 14
RSI_BUY_ZONE_LOW = 35.0
RSI_BUY_ZONE_HIGH = 52.0

# 7. VAQT ZONASI VA KUNLIK HISOBOT
# VPS odatda UTC da ishlaydi. Kunlik limit va 20:00 hisobot O'zbekiston vaqti (UTC+5) bo'yicha hisoblanadi.
TZ_OFFSET_HOURS = float(os.getenv("TZ_OFFSET_HOURS", "5"))
LOCAL_TZ = timezone(timedelta(hours=TZ_OFFSET_HOURS))
DAILY_REPORT_HOUR = 20

# 8. FAYLLAR
STATE_FILE = os.getenv(
    "STATE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json"),
)

# 9. API KALITLAR (faqat muhit o'zgaruvchilari yoki .env orqali!)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def local_now() -> datetime:
    """Bot ichidagi barcha vaqtlar uchun yagona soat (O'zbekiston vaqti)."""
    return datetime.now(LOCAL_TZ)


def validate() -> None:
    """Sozlamalardagi o'zaro zid qiymatlarni ishga tushishdan oldin aniqlaydi."""
    errors = []
    if SYMBOL not in ALLOWED_SYMBOLS:
        errors.append(f"SYMBOL={SYMBOL} ruxsat etilgan ro'yxatda yo'q")
    if not 0 < RISK_PER_TRADE_PCT <= 0.05:
        errors.append("RISK_PER_TRADE_PCT 0..5% oralig'ida bo'lishi kerak")
    if not 0 < STOP_LOSS_DISTANCE_PCT < 0.5:
        errors.append("STOP_LOSS_DISTANCE_PCT noto'g'ri")
    if MAX_POSITION_CAPITAL_PCT * MAX_CONCURRENT_POSITIONS > 1.0:
        errors.append("MAX_POSITION_CAPITAL_PCT x MAX_CONCURRENT_POSITIONS 100% dan oshmasligi kerak (Spot'da qarz yo'q)")
    if RISK_PER_TRADE_PCT * MAX_CONCURRENT_POSITIONS > MAX_DAILY_LOSS_PCT:
        errors.append("Barcha ochiq bitimlar riski kunlik limitdan katta")
    if KLINE_LIMIT < SLOW_EMA_PERIOD + 2 or KLINE_LIMIT > 999:
        errors.append("KLINE_LIMIT SLOW_EMA_PERIOD+2 .. 999 oralig'ida bo'lishi kerak")
    if errors:
        raise ValueError("Sozlamalarda xato: " + "; ".join(errors))
