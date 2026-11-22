"""
Interaktiv Telegram Boshqaruv va Kunlik Qat'iy Matematik Spot Hisobot Moduli.
Sun'iy intellektsiz, 100% aniq matematik qoidalar va indikatorlar (EMA 20/50, RSI 14, 1% Risk) asosida ishlaydi.

Qo'llab-quvvatlanadigan Telegram buyruqlari:
  /status     - Spot balans, ochiq bitimlar (#1, #2), joriy foyda/zarar va kunlik limit holati
  /buy (/add) - Yangi bitim ochish yoki ishlab turgan 1-bitim ustiga 2-bitimni qo'shish (1% risk bilan)
  /close <id> - Bitimni hozirgi narxda yopish (masalan: /close 1 yoki /close all)
  /report     - Kunlik qat'iy matematik Spot tahlil (EMA trend, RSI impuls va bitim holati)
  /pause      - Avtomatik bitim ochishni vaqtincha to'xtatish
  /resume     - Avtomatik bitim ochishni qayta yoqish
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import config
from bot_context import BotContext


def _md(text: object) -> str:
    """Telegram Markdown'ni buzadigan belgilarni (_, *, `, [) olib tashlaydi."""
    return str(text).replace("_", " ").replace("*", "").replace("`", "'").replace("[", "(")


def fmt_usd(value: float) -> str:
    return f"${value:,.2f}" if value >= 1 else f"${value:.6f}"


class TelegramController:
    def __init__(self) -> None:
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = str(config.TELEGRAM_CHAT_ID).strip()
        self.last_update_id = 0
        # Bot o'chiq turganda yuborilgan eski buyruqlar (masalan, kechagi /buy) bajarilmasligi uchun
        self.started_at = time.time()

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------ tarmoq

    def _api(self, method: str, params: dict, timeout: float) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_message(self, text: str) -> None:
        if not self.is_configured:
            return
        try:
            self._api("sendMessage", {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}, timeout=8)
        except urllib.error.HTTPError as exc:
            # 400 odatda Markdown xatosi — xabar yo'qolmasligi uchun oddiy matn sifatida qayta yuboramiz
            if exc.code == 400:
                try:
                    self._api("sendMessage", {"chat_id": self.chat_id, "text": text}, timeout=8)
                    return
                except Exception as exc2:  # noqa: BLE001
                    exc = exc2
            print(f"[Telegram Xatolik] Xabar yuborilmadi: {exc}")
        except Exception as exc:  # noqa: BLE001
            # Xato matnida token bo'lishi mumkin emas (URL chop etilmaydi)
            print(f"[Telegram Xatolik] Xabar yuborilmadi: {type(exc).__name__}: {exc}")

    def fetch_updates(self) -> list[dict]:
        """Yangi xabarlarni oladi (tarmoq so'rovi — qulf ushlab turilmasdan chaqiriladi)."""
        if not self.is_configured:
            return []
        try:
            data = self._api("getUpdates", {"offset": self.last_update_id + 1, "timeout": 1}, timeout=6)
        except Exception as exc:  # noqa: BLE001
            print(f"[Telegram Xatolik] Buyruqlarni olib bo'lmadi: {type(exc).__name__}")
            return []

        updates = data.get("result", [])
        if updates:
            self.last_update_id = max(u["update_id"] for u in updates)

        fresh = [u for u in updates if (u.get("message") or {}).get("date", 0) >= self.started_at - 5]
        skipped = len(updates) - len(fresh)
        if skipped:
            print(f"[Telegram] Bot ishga tushishidan oldin kelgan {skipped} ta eski xabar o'tkazib yuborildi.")
        return fresh

    def handle_updates(self, updates: list[dict], ctx: BotContext, now_str: str) -> None:
        for item in updates:
            msg = item.get("message") or {}
            sender_chat_id = str((msg.get("chat") or {}).get("id", ""))
            if sender_chat_id != self.chat_id:
                continue  # Faqat egasining chatidan kelgan buyruqlar bajariladi
            text = (msg.get("text") or "").strip()
            if not text.startswith("/"):
                continue
            try:
                self._handle_command(text, ctx, now_str)
            except Exception as exc:  # noqa: BLE001
                self.send_message(f"⚠️ Buyruqni bajarishda xato: {_md(exc)}")

    # ------------------------------------------------------------------ buyruqlar

    def _handle_command(self, text: str, ctx: BotContext, now_str: str) -> None:
        parts = text.split()
        cmd = parts[0].lower().split("@", 1)[0]  # "/status@MyBot" -> "/status"
        rm = ctx.rm

        if cmd in ("/start", "/help"):
            self.send_message(
                "🤖 *Quant Spot Trading Bot Boshqaruv Paneli*\n\n"
                "📊 `/status` — Spot balans va ochiq bitimlar holati\n"
                "➕ `/add` yoki `/buy` — Yangi (yoki 2-qo'shimcha) bitim ochish\n"
                "❌ `/close 1` yoki `/close all` — Ochiq bitimni darhol yopish\n"
                "📈 `/report` — Matematik indikatorlar va Spot bozor hisoboti\n"
                "⏸ `/pause` — Avto-savdoni to'xtatish\n"
                "▶️ `/resume` — Avto-savdoni davom ettirish"
            )

        elif cmd == "/status":
            self.send_message(self.format_status_report(ctx))

        elif cmd in ("/buy", "/add"):
            ok, reason, pos = ctx.open_manual("TELEGRAM_MANUAL", now_str)
            if not ok or pos is None:
                self.send_message(f"⚠️ *Bitim qo'shish rad etildi:*\n{_md(reason)}")
                return
            self.send_message(
                f"✅ *TELEGRAM ORQALI #{pos.position_id}-BITIM OCHILDI!* ({self.mode_label()})\n"
                f"• Aktiv: `{pos.symbol}` (Spot)\n"
                f"• Kirish narxi: `{fmt_usd(pos.entry_price)}`\n"
                f"• Ajratilgan mablag': `${pos.position_value_usdt:.2f}` "
                f"({pos.position_value_usdt * config.UZS_PER_USD:,.0f} so'm)\n"
                f"• {self.sl_label()}: `{fmt_usd(pos.stop_loss_price)}` "
                f"(-{pos.max_risk_usdt * config.UZS_PER_USD:,.0f} so'm)\n"
                f"• {self.tp_label()}: `{fmt_usd(pos.take_profit_price)}` "
                f"(+{pos.expected_reward_usdt * config.UZS_PER_USD:,.0f} so'm)\n"
                f"• Jami faol bitimlar: `{len(rm.open_positions)}/{config.MAX_CONCURRENT_POSITIONS}`"
            )

        elif cmd == "/close":
            if not rm.open_positions:
                self.send_message("ℹ️ Hozir yopish uchun ochiq bitim yo'q.")
                return
            if len(parts) < 2:
                # Oldin argument berilmasa jimgina HAMMA bitim yopilardi — bu xavfli edi
                ids = ", ".join(str(p.position_id) for p in rm.open_positions)
                self.send_message(f"ℹ️ Qaysi bitimni yopish kerak? Masalan: `/close 1` yoki `/close all`\nOchiq: {ids}")
                return
            arg = parts[1].lower()
            if arg == "all":
                records, errors = ctx.close_all("TELEGRAM_CLOSE", now_str)
                lines = ["🔒 *Ochiq bitimlar yopildi:*"]
                for rec in records:
                    lines.append(
                        f"• Bitim #{rec['position_id']}: `{rec['pnl_uzs']:+,.0f} so'm` ({rec['pnl_usdt']:+.2f} USDT)"
                    )
                lines.extend(f"⚠️ {_md(e)}" for e in errors)
                self.send_message("\n".join(lines))
            else:
                try:
                    pid = int(arg.lstrip("#"))
                except ValueError:
                    self.send_message("⚠️ Bitim raqami noto'g'ri. Masalan: `/close 1`")
                    return
                try:
                    rec = ctx.close_one(pid, "TELEGRAM_CLOSE", now_str)
                except ValueError as exc:
                    self.send_message(f"⚠️ Xato: {_md(exc)}")
                    return
                self.send_message(
                    f"🔒 *Bitim #{pid} qo'lda yopildi!*\n"
                    f"• Natija: `{rec['pnl_uzs']:+,.0f} so'm` ({rec['pnl_usdt']:+.2f} USDT, komissiya bilan)\n"
                    f"• Yangi balans: `{rec['balance_after_uzs']:,.0f} so'm`"
                )

        elif cmd in ("/report", "/ai"):
            self.send_message(self.generate_daily_quant_review(ctx))

        elif cmd == "/pause":
            with ctx.lock:
                rm.auto_trading_paused = True
            self.send_message("⏸ *Avtomatik bitim ochish to'xtatildi.* (Ochiq bitimlar SL/TP nazoratida qoladi).")

        elif cmd == "/resume":
            with ctx.lock:
                rm.auto_trading_paused = False
            self.send_message("▶️ *Avtomatik bitim ochish qayta yoqildi.*")

        else:
            self.send_message("❓ Noma'lum buyruq. Ro'yxat uchun /help yuboring.")

    # ------------------------------------------------------------------ matnlar

    @staticmethod
    def mode_label() -> str:
        return "VIRTUAL" if config.PAPER_TRADING else "LIVE"

    @staticmethod
    def sl_label() -> str:
        return f"Stop-Loss (narx -{config.STOP_LOSS_DISTANCE_PCT * 100:.2f}%, balansning -{config.RISK_PER_TRADE_PCT * 100:.0f}%)"

    @staticmethod
    def tp_label() -> str:
        tp = config.STOP_LOSS_DISTANCE_PCT * config.REWARD_TO_RISK_RATIO * 100
        return f"Take-Profit (narx +{tp:.2f}%)"

    def format_status_report(self, ctx: BotContext) -> str:
        with ctx.lock:
            rm = ctx.rm
            price = ctx.price(config.SYMBOL)
            bal_uzs = rm.balance_usdt * config.UZS_PER_USD
            daily_uzs = rm.daily_realized_pnl_usdt * config.UZS_PER_USD
            lines = [
                f"📊 *SPOT PORTFEL HOLATI ({config.SYMBOL} • {self.mode_label()})*",
                f"• Joriy narx: `{fmt_usd(price) if price else 'yuklanmoqda...'}`",
                f"• Umumiy balans: `{bal_uzs:,.0f} so'm` (`${rm.balance_usdt:.2f}`)",
                f"• Bo'sh mablag': `${rm.free_capital_usdt:.2f}` | Band: `${rm.used_capital_usdt:.2f}`",
                f"• Bugungi natija: `{daily_uzs:+,.0f} so'm` (`{rm.daily_realized_pnl_usdt:+.2f} USDT`)",
                f"• Kill-Switch (3% limit): `{'🛑 YOQILGAN' if rm.kill_switch_active else '🟢 XAVFSIZ'}`",
                f"• Avto-savdo: `{'⏸ PAUZA' if rm.auto_trading_paused else '▶️ YONIQ'}`",
                f"• Ochiq bitimlar: `{len(rm.open_positions)}/{config.MAX_CONCURRENT_POSITIONS}`",
            ]
            for p in rm.open_positions:
                p_price = ctx.price(p.symbol)
                if p_price:
                    unrealized_uzs = (p_price - p.entry_price) * p.quantity * config.UZS_PER_USD
                    pnl_str = f"{unrealized_uzs:+,.0f} so'm"
                else:
                    pnl_str = "narx yo'q"
                lines.append(
                    f"\n🔹 *Bitim #{p.position_id}* (`{p.symbol}` • `{p.source}`)\n"
                    f"  Kirish: `{fmt_usd(p.entry_price)}` | Hozir: `{pnl_str}`\n"
                    f"  SL: `{fmt_usd(p.stop_loss_price)}` | TP: `{fmt_usd(p.take_profit_price)}`"
                )
        return "\n".join(lines)

    def generate_daily_quant_review(self, ctx: BotContext) -> str:
        """
        Spot portfel va bozor holatini qat'iy matematik mezonlar
        (EMA 20/50, RSI 14, Risk-Menejment) asosida hisobot qilib chiqaradi.
        """
        with ctx.lock:
            rm = ctx.rm
            symbol = config.SYMBOL
            price = ctx.price(symbol)
            metrics = ctx.metrics(symbol)
            fast_ema = metrics.get("fast_ema")
            slow_ema = metrics.get("slow_ema")
            rsi = metrics.get("rsi")
            balance_uzs = rm.balance_usdt * config.UZS_PER_USD
            daily_uzs = rm.daily_realized_pnl_usdt * config.UZS_PER_USD
            open_count = len(rm.open_positions)
            kill = rm.kill_switch_active
            trades_today = rm.trades_today

        if fast_ema is None or slow_ema is None or rsi is None or price is None:
            return f"📐 *KUNLIK MATEMATIK SPOT HISOBOT*\n\nAktiv: `{symbol}` — bozor ma'lumotlari hali yuklanmagan."

        trend_str = "O'SUVCHI (EMA20 > EMA50)" if fast_ema > slow_ema else "PASAYUVCHI (EMA20 <= EMA50)"
        low, high = config.RSI_BUY_ZONE_LOW, config.RSI_BUY_ZONE_HIGH
        if rsi < low:
            rsi_state = f"Haddan tashqari sotilgan (<{low:.0f})"
        elif rsi <= high:
            rsi_state = f"Kirish zonasida ({low:.0f}..{high:.0f})"
        elif rsi < 70:
            rsi_state = f"O'sish impulsida ({high:.0f}..70)"
        else:
            rsi_state = "Qizigan zonada (>70)"

        if kill:
            rule_status = "🛑 Kunlik 3% limit to'lgan. Savdo ertagacha avtomatik bloklangan."
        elif metrics.get("signal"):
            rule_status = "🟢 Barcha 3 ta matematik shart bajarilgan (Trend + RSI zonasi + tiklanish shamchasi)."
        else:
            rule_status = "⏳ Matematik kirish shartlari hali to'liq bajarilmadi (kutish rejimi)."

        return (
            f"📐 *KUNLIK MATEMATIK SPOT HISOBOT*\n\n"
            f"• Aktiv: `{symbol}` | Narx: `{fmt_usd(price)}`\n"
            f"• Trend filtri: *{trend_str}* (`{fast_ema}` / `{slow_ema}`)\n"
            f"• Impuls filtri (RSI 14): `{rsi}` — *{rsi_state}*\n"
            f"• Faol bitimlar: `{open_count}/{config.MAX_CONCURRENT_POSITIONS}` | Bugun yopilgan: `{trades_today}`\n"
            f"• Bugungi natija: `{daily_uzs:+,.0f} so'm`\n"
            f"• Balans: `{balance_uzs:,.0f} so'm`\n\n"
            f"📌 *Algoritm holati:*\n{rule_status}"
        )
