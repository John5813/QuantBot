"""
Interaktiv Telegram Boshqaruv va Kunlik Qat'iy Matematik Spot Hisobot Moduli.
Sun'iy intellektsiz, 100% aniq matematik qoidalar va indikatorlar (EMA 20/50, RSI 14, 1% Risk) asosida ishlaydi.

Qo'llab-quvvatlanadigan Telegram buyruqlari:
  /status    - Spot balans, ochiq bitimlar (#1, #2), joriy foyda/zarar va kunlik limit holati
  /buy (/add)- Yangi bitim ochish yoki ishlab turgan 1-bitim ustiga 2-bitimni qo'shish (1% risk bilan)
  /close <id>- Bitimni hozirgi narxda yopish (masalan: /close 1 yoki /close all)
  /report    - Kunlik qat'iy matematik Spot tahlil (EMA trend, RSI impuls va bitim holati)
  /pause     - Avtomatik bitim ochishni vaqtincha to'xtatish
  /resume    - Avtomatik bitim ochishni qayta yoqish
"""

import json
import urllib.parse
import urllib.request
import config
from risk_manager import RiskManager


class TelegramController:
    def __init__(self) -> None:
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = str(config.TELEGRAM_CHAT_ID)
        self.last_update_id = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_message(self, text: str) -> None:
        if not self.is_configured:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=payload)
            urllib.request.urlopen(req, timeout=8)
        except Exception as exc:
            print(f"[Telegram Xatolik] Xabar yuborilmadi: {exc}")

    def poll_commands(
        self,
        rm: RiskManager,
        current_price: float,
        metrics: dict,
        now_str: str,
    ) -> None:
        """Telegramdan kelgan buyruqlarni o'qiydi va bajaradi."""
        if not self.is_configured:
            return

        url = (
            f"https://api.telegram.org/bot{self.token}/getUpdates"
            f"?offset={self.last_update_id + 1}&timeout=1"
        )
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return

        for item in data.get("result", []):
            self.last_update_id = item["update_id"]
            msg = item.get("message", {})
            sender_chat_id = str(msg.get("chat", {}).get("id", ""))
            if sender_chat_id != self.chat_id:
                continue

            text = (msg.get("text") or "").strip()
            if not text.startswith("/"):
                continue

            self._handle_command(text, rm, current_price, metrics, now_str)

    def _handle_command(
        self,
        text: str,
        rm: RiskManager,
        current_price: float,
        metrics: dict,
        now_str: str,
    ) -> None:
        parts = text.split()
        cmd = parts[0].lower()

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
            self.send_message(self.format_status_report(rm, current_price))

        elif cmd in ("/buy", "/add"):
            allowed, reason = rm.can_open_trade(is_manual_add=True)
            if not allowed:
                self.send_message(f"⚠️ *Bitim qo'shish rad etildi:*\n{reason}")
                return
            pos = rm.open_new_position(current_price, now_str, source="TELEGRAM_MANUAL")
            self.send_message(
                f"✅ *TELEGRAM ORQALI #{pos.position_id}-BITIM OCHILDI!*\n"
                f"• Aktiv: `{pos.symbol}` (Spot)\n"
                f"• Kirish narxi: `${pos.entry_price}`\n"
                f"• Ajratilgan mablag': `${pos.position_value_usdt}` "
                f"({pos.position_value_usdt * config.UZS_PER_USD:,.0f} so'm)\n"
                f"• Stop-Loss (-1% risk): `${pos.stop_loss_price}` "
                f"(-{pos.max_risk_usdt * config.UZS_PER_USD:,.0f} so'm)\n"
                f"• Take-Profit (+2% foyda): `${pos.take_profit_price}` "
                f"(+{pos.expected_reward_usdt * config.UZS_PER_USD:,.0f} so'm)\n"
                f"• Jami faol bitimlar: `{len(rm.open_positions)}/{config.MAX_CONCURRENT_POSITIONS}`"
            )

        elif cmd == "/close":
            if not rm.open_positions:
                self.send_message("ℹ️ Hozir yopish uchun ochiq bitim yo'q.")
                return
            arg = parts[1].lower() if len(parts) > 1 else "all"
            if arg == "all":
                ids = [p.position_id for p in list(rm.open_positions)]
                lines = ["🔒 *Barcha ochiq bitimlar yopildi:*"]
                for pid in ids:
                    rec = rm.close_position_by_id(pid, current_price, "TELEGRAM_CLOSE", now_str)
                    lines.append(
                        f"• Bitim #{pid}: `{rec['pnl_uzs']:+,.0f} so'm` ({rec['pnl_usdt']:+.2f} USDT)"
                    )
                self.send_message("\n".join(lines))
            else:
                try:
                    pid = int(arg)
                    rec = rm.close_position_by_id(pid, current_price, "TELEGRAM_CLOSE", now_str)
                    self.send_message(
                        f"🔒 *Bitim #{pid} qo'lda yopildi!*\n"
                        f"• Natija: `{rec['pnl_uzs']:+,.0f} so'm` ({rec['pnl_usdt']:+.2f} USDT)\n"
                        f"• Yangi balans: `{rec['balance_after_uzs']:,.0f} so'm`"
                    )
                except Exception as exc:
                    self.send_message(f"⚠️ Xato: {exc}")

        elif cmd in ("/report", "/ai"):
            report = self.generate_daily_quant_review(rm, current_price, metrics)
            self.send_message(report)

        elif cmd == "/pause":
            rm.auto_trading_paused = True
            self.send_message("⏸ *Avtomatik bitim ochish to'xtatildi.* (Ochiq bitimlar SL/TP nazoratida qoladi).")

        elif cmd == "/resume":
            rm.auto_trading_paused = False
            self.send_message("▶️ *Avtomatik bitim ochish qayta yoqildi.*")

    def format_status_report(self, rm: RiskManager, current_price: float) -> str:
        bal_uzs = rm.balance_usdt * config.UZS_PER_USD
        daily_uzs = rm.daily_realized_pnl_usdt * config.UZS_PER_USD
        lines = [
            f"📊 *SPOT PORTFEL HOLATI ({config.SYMBOL})*",
            f"• Joriy narx: `${current_price}`",
            f"• Umumiy balans: `{bal_uzs:,.0f} so'm` (`${rm.balance_usdt:.2f}`)",
            f"• Bo'sh mablag': `${rm.free_capital_usdt:.2f}` | Band: `${rm.used_capital_usdt:.2f}`",
            f"• Bugungi natija: `{daily_uzs:+,.0f} so'm` (`{rm.daily_realized_pnl_usdt:+.2f} USDT`)",
            f"• Kill-Switch (3% limit): `{'🛑 YOQILGAN' if rm.kill_switch_active else '🟢 XAVFSIZ'}`",
            f"• Ochiq bitimlar: `{len(rm.open_positions)}/{config.MAX_CONCURRENT_POSITIONS}`",
        ]
        for p in rm.open_positions:
            unrealized_usdt = (current_price - p.entry_price) * p.quantity
            unrealized_uzs = unrealized_usdt * config.UZS_PER_USD
            lines.append(
                f"\n🔹 *Bitim #{p.position_id} ({p.source})*\n"
                f"  Kirish: `${p.entry_price}` | Hozir: `{unrealized_uzs:+,.0f} so'm`\n"
                f"  SL: `${p.stop_loss_price}` | TP: `${p.take_profit_price}`"
            )
        return "\n".join(lines)

    def generate_daily_quant_review(
        self,
        rm: RiskManager,
        current_price: float,
        metrics: dict,
    ) -> str:
        """
        Har kuni Spot portfel va bozor holatini qat'iy matematik mezonlar
        (EMA 20/50, RSI 14, Risk-Menejment) asosida hisobot qilib chiqaradi.
        """
        fast_ema = metrics.get("fast_ema") or current_price
        slow_ema = metrics.get("slow_ema") or current_price
        rsi = metrics.get("rsi") or 50.0

        trend_str = "O'SUVCHI (EMA20 > EMA50)" if fast_ema > slow_ema else "PASAYUVCHI (EMA20 < EMA50)"
        if rsi < 35:
            rsi_state = "Haddan tashqari sotilgan (<35)"
        elif rsi <= 52:
            rsi_state = "Kirish zonasida (35..52)"
        elif rsi < 70:
            rsi_state = "O'sish impulsida (52..70)"
        else:
            rsi_state = "Qizigan zonada (>70)"

        if rm.kill_switch_active:
            rule_status = "🛑 Kunlik 3% limit to'lgan. Savdo ertagacha avtomatik bloklangan."
        elif fast_ema > slow_ema and 35 <= rsi <= 52:
            rule_status = "🟢 Barcha matematik shartlar bajarilgan (Trend + RSI kirish zonasida)."
        else:
            rule_status = "⏳ Matematik kirish shartlari hali to'liq bajarilmadi (kutish rejimi)."

        return (
            f"📐 *KUNLIK MATEMATIK SPOT HISOBOT*\n\n"
            f"• Aktiv: `{config.SYMBOL}` | Narx: `${current_price}`\n"
            f"• Trend filtri: *{trend_str}* (`{fast_ema}` / `{slow_ema}`)\n"
            f"• Impuls filtri (RSI 14): `{rsi}` — *{rsi_state}*\n"
            f"• Faol bitimlar: `{len(rm.open_positions)}/{config.MAX_CONCURRENT_POSITIONS}`\n"
            f"• Balans: `{rm.balance_usdt * config.UZS_PER_USD:,.0f} so'm`\n\n"
            f"📌 *Algoritm holati:*\n{rule_status}"
        )
