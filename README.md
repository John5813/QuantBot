# Lightweight Quant Trading Bot (1,000,000 UZS / ~$78 USDT)

Ushbu bot **Binance Spot** bozorida (`PAXGUSDT` — oltin, `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`)
qat'iy **1% Risk-Menejment** va **3% Kunlik Kill-Switch** qoidalari asosida ishlash uchun yaratilgan.

> ⚠️ **Hozircha faqat VIRTUAL (paper trading) rejim ishlaydi.** Real Binance buyurtma yuborish moduli
> yozilmagan. `PAPER_TRADING=false` qilinsa bot ataylab ishga tushmaydi — aks holda "LIVE" deb yozib,
> aslida pulsiz savdo qilib, sizni chalg'itardi.

## Qoidalar (config.py)
| Qoida | Qiymat |
|---|---|
| Bitta bitim xavfi | balansning **1%** (~10,000 so'm), Binance komissiyasi (0.1% + 0.1%) bilan birga |
| Stop-Loss | kirish narxidan **−2.08%** |
| Take-Profit | kirish narxidan **+4.16%** (1:2) |
| Bitim hajmi | balansning ~44% i (1% risk / (2.08% + komissiya)), ko'pi bilan 48% |
| Kunlik limit | **−3%** — yetilsa ertagacha (O'zbekiston vaqti bilan) yangi bitim ochilmaydi |
| Parallel bitimlar | avtomatik 1 ta, qo'lda (Telegram/Veb) 2 tagacha |
| Strategiya | EMA20 > EMA50, narx > EMA50, RSI(14) 35..52, oxirgi shamcha o'suvchi — faqat **yopilgan** shamchalarda |

## VPS Resurs talablari
- **RAM:** ~20 MB (faqat Python standart kutubxonalari, `pip install` shart emas). Python 3.9+.
- **Disk:** `bot_state.json` (oxirgi 500 ta bitim).
- **CPU:** < 1% (har 15 soniyada Binance'ga 1 ta yengil so'rov; Avto-Skaner yoqilsa 5 ta).

## Loyiha fayllari
- `config.py` — barcha sozlamalar; mahfiy qiymatlar `.env` dan o'qiladi.
- `risk_manager.py` — pozitsiya hajmi, SL/TP, komissiya, kunlik Kill-Switch, holatni saqlash/tiklash.
- `strategy.py` — EMA 20/50 trend filtri va RSI 14 pullback signali.
- `market_data.py` — Binance ochiq API'dan shamchalarni olish (bot va backtest uchun umumiy).
- `bot_context.py` — bot, Telegram va veb-panel o'rtasidagi umumiy holat (oqimlar uchun qulf bilan).
- `bot.py` — 24/7 ishlaydigan asosiy dastur.
- `telegram_controller.py` — Telegram buyruqlari va kunlik hisobot.
- `web_dashboard.py` — veb boshqaruv paneli (token bilan himoyalangan).
- `backtest.py` — tarixiy sinov (standart: oxirgi 30 kun).
- `dashboard_preview.html` — serversiz, brauzerda ochiladigan simulyator (bot bilan bir xil qoidalar).
- `tests/` — tarmoqsiz testlar.

## O'rnatish

1. Fayllarni VPS'ga ko'chiring (masalan, `/root/trading-bot`).
2. Sozlamalar faylini yarating va to'ldiring:
   ```bash
   cp .env.example .env
   ```
   ```bash
   nano .env
   ```
3. Testlarni ishga tushiring:
   ```bash
   python3 -m unittest discover -s tests
   ```
4. Tarixiy sinov (Backtest). Ixtiyoriy argumentlar: aktiv va kunlar soni:
   ```bash
   python3 backtest.py PAXGUSDT 30
   ```
   > Diqqat: Binance ba'zi mamlakatlar (masalan, AQSh) serverlaridan `451` xatosi bilan javob bermaydi.
   > Bunday holda backtest TASODIFIY oflayn ma'lumotlarda ishlaydi — uning natijasi haqiqiy emas.

## `screen` orqali ishga tushirish

```bash
screen -S trading_bot
```
```bash
python3 bot.py
```
- Orqa fonga o'tkazish: `Ctrl + A`, keyin `D`.
- Qayta kirish:
  ```bash
  screen -r trading_bot
  ```
- Bot `Ctrl + C` yoki `kill` bilan to'xtatilsa, holatni saqlab chiqadi. Qayta ishga tushganda balans,
  ochiq bitimlar va kunlik Kill-Switch holati `bot_state.json` dan tiklanadi.

## Veb-panel
- Standart holatda faqat serverning o'zida ochiladi. Kompyuteringizdan SSH tunnel orqali kiring:
  ```bash
  ssh -L 8080:127.0.0.1:8080 root@<VPS_IP>
  ```
  So'ng brauzerda: `http://localhost:8080`
- Internetdan to'g'ridan-to'g'ri ochish kerak bo'lsa, `.env` da `WEB_HOST=0.0.0.0` va
  `WEB_DASHBOARD_TOKEN=<uzun tasodifiy satr>` qo'ying. Manzil: `http://<VPS_IP>:8080/?token=<TOKEN>`.
  Token o'rnatilmasa, panel xavfsizlik uchun baribir faqat 127.0.0.1 da ochiladi.
  (Diqqat: oddiy HTTP shifrlanmagan — imkon bo'lsa SSH tunnel yoki HTTPS reverse-proxy ishlating.)

## Telegram buyruqlari
| Buyruq | Vazifasi |
|---|---|
| `/status` | Balans, ochiq bitimlar, kunlik natija |
| `/add` yoki `/buy` | Tanlangan aktivda qo'lda bitim ochish (2-bitim ham) |
| `/close 1` / `/close all` | Bitta yoki barcha bitimlarni yopish |
| `/report` | Indikatorlar bo'yicha hisobot (har kuni 20:00 da avtomatik ham keladi) |
| `/pause`, `/resume` | Avtomatik bitim ochishni to'xtatish / yoqish |

Bot faqat `TELEGRAM_CHAT_ID` dagi chatdan kelgan buyruqlarni bajaradi; bot o'chiq paytda yuborilgan
eski buyruqlar e'tiborsiz qoldiriladi.
