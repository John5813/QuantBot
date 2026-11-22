"""
Tarmoqsiz (offline) testlar: python3 -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import time
import unittest
import urllib.request
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import bot  # noqa: E402
from bot_context import BotContext  # noqa: E402
from risk_manager import RiskManager  # noqa: E402
from strategy import calculate_ema, calculate_rsi, ema_series  # noqa: E402
from telegram_controller import TelegramController  # noqa: E402


def make_klines(prices, interval_ms=900_000, forming=True):
    """Binance /klines formatidagi javob. Oxirgisi hozir shakllanayotgan shamcha bo'ladi."""
    now_ms = int(time.time() * 1000)
    n = len(prices)
    start = now_ms - (n - (1 if forming else 0)) * interval_ms - 1000
    out = []
    for i, p in enumerate(prices):
        ot = start + i * interval_ms
        out.append([ot, str(p), str(p * 1.001), str(p * 0.999), str(p), "0", ot + interval_ms - 1])
    return out


def parsed(prices, forming=True):
    from market_data import _parse_kline
    return [_parse_kline(k) for k in make_klines(prices, forming=forming)]


class RiskManagerTests(unittest.TestCase):
    def setUp(self):
        self.symbol = "PAXGUSDT"

    def test_stop_loss_loses_at_most_one_percent_with_fees(self):
        rm = RiskManager()
        start = rm.balance_usdt
        pos = rm.open_new_position(2000.0, "t", symbol=self.symbol)
        rec = rm.close_position_by_id(pos.position_id, pos.stop_loss_price, "SL", "t")
        loss_pct = -rec["pnl_usdt"] / start
        self.assertLessEqual(loss_pct, config.RISK_PER_TRADE_PCT * 1.001)
        self.assertGreater(loss_pct, config.RISK_PER_TRADE_PCT * 0.98)

    def test_take_profit_is_net_positive(self):
        rm = RiskManager()
        pos = rm.open_new_position(2000.0, "t", symbol=self.symbol)
        rec = rm.close_position_by_id(pos.position_id, pos.take_profit_price, "TP", "t")
        self.assertGreater(rec["pnl_usdt"], 0)
        self.assertGreater(rec["fees_usdt"], 0)

    def test_auto_only_one_manual_two(self):
        rm = RiskManager()
        rm.open_new_position(2000.0, "t", symbol=self.symbol)
        self.assertFalse(rm.can_open_trade(is_manual_add=False)[0])
        self.assertTrue(rm.can_open_trade(is_manual_add=True)[0])
        rm.open_new_position(2000.0, "t", symbol=self.symbol)
        self.assertFalse(rm.can_open_trade(is_manual_add=True)[0])
        self.assertLessEqual(rm.used_capital_usdt, rm.balance_usdt)

    def test_kill_switch_blocks_and_resets_next_day(self):
        rm = RiskManager(current_day=date(2026, 1, 1))
        for _ in range(3):
            pos = rm.open_new_position(2000.0, "t", symbol=self.symbol)
            rm.close_position_by_id(pos.position_id, pos.stop_loss_price * 0.995, "SL", "t")
        allowed, reason = rm.can_open_trade(simulated_date=date(2026, 1, 1))
        self.assertFalse(allowed)
        self.assertTrue(rm.kill_switch_active)
        self.assertTrue(rm.can_open_trade(simulated_date=date(2026, 1, 2))[0])

    def test_rejects_bad_price_and_symbol(self):
        rm = RiskManager()
        with self.assertRaises(ValueError):
            rm.open_new_position(0, "t", symbol=self.symbol)
        with self.assertRaises(ValueError):
            rm.open_new_position(100, "t", symbol="DOGEUSDT")

    def test_state_roundtrip(self):
        rm = RiskManager()
        rm.open_new_position(2000.0, "t", symbol=self.symbol)
        pos = rm.open_new_position(2000.0, "t", symbol=self.symbol)
        rm.close_position_by_id(pos.position_id, 2010.0, "X", "t")
        rm2 = RiskManager.from_state(json.loads(json.dumps(rm.to_state())))
        self.assertAlmostEqual(rm2.balance_usdt, rm.balance_usdt)
        self.assertEqual(len(rm2.open_positions), 1)
        self.assertEqual(rm2.next_position_id, rm.next_position_id)


class StrategyTests(unittest.TestCase):
    def test_ema_matches_series(self):
        prices = [float(i) for i in range(1, 80)]
        self.assertAlmostEqual(calculate_ema(prices, 20), round(ema_series(prices, 20)[-1], 4))
        self.assertIsNone(calculate_ema(prices[:5], 20))

    def test_rsi_bounds(self):
        self.assertEqual(calculate_rsi([1.0] * 30), 50.0)
        self.assertEqual(calculate_rsi([float(i) for i in range(30)]), 100.0)
        self.assertLess(calculate_rsi([float(30 - i) for i in range(30)]), 1.0)


class BotLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.tmp.name, "state.json")
        self._orig = (config.SYMBOL, config.AUTO_SCAN_MARKETS, config.STATE_FILE)
        config.SYMBOL = "PAXGUSDT"
        config.AUTO_SCAN_MARKETS = False
        self.prices = {"PAXGUSDT": 2000.0, "BTCUSDT": 90000.0}

    def tearDown(self):
        config.SYMBOL, config.AUTO_SCAN_MARKETS, config.STATE_FILE = self._orig
        self.tmp.cleanup()

    def fake_fetch(self, symbol, interval, limit=500, **_):
        p = self.prices.get(symbol, 100.0)
        return parsed([p] * limit)

    def test_position_checked_against_its_own_symbol(self):
        """Oldin: PAXG bitimi ochiq turganda BTC tanlansa, BTC narxi bilan TP 'urilib' soxta foyda chiqardi."""
        ctx = BotContext(RiskManager())
        tg = TelegramController()
        with mock.patch("bot.fetch_klines", self.fake_fetch):
            bot.refresh_market(ctx)
            ok, _, pos = ctx.open_manual("TEST", "t")
            self.assertTrue(ok)
            ctx.set_symbol("BTCUSDT")
            bot.refresh_market(ctx)
            bot.check_exits(ctx, tg, "t")
        self.assertEqual(len(ctx.rm.open_positions), 1, "PAXG bitimi BTC narxi bilan yopilib ketmasligi kerak")
        self.assertEqual(pos.symbol, "PAXGUSDT")

    def test_manual_open_requires_fresh_price(self):
        ctx = BotContext(RiskManager())
        ok, reason, _ = ctx.open_manual("TEST", "t")
        self.assertFalse(ok)
        self.assertIn("narx", reason)

    def test_no_reentry_on_same_candle(self):
        ctx = BotContext(RiskManager())
        tg = TelegramController()
        signals = {"PAXGUSDT": {"enter": True, "candle_time": 123, "price": 2000.0}}
        with mock.patch("bot.fetch_klines", self.fake_fetch):
            bot.refresh_market(ctx)
        bot.try_auto_entry(ctx, tg, signals, "t")
        self.assertEqual(len(ctx.rm.open_positions), 1)
        pos = ctx.rm.open_positions[0]
        ctx.rm.close_position_by_id(pos.position_id, pos.stop_loss_price, "SL", "t")
        bot.try_auto_entry(ctx, tg, signals, "t")
        self.assertEqual(len(ctx.rm.open_positions), 0, "Xuddi shu shamcha signali bilan qayta kirmasligi kerak")

    def test_save_and_load_state(self):
        ctx = BotContext(RiskManager())
        with mock.patch("bot.fetch_klines", self.fake_fetch):
            bot.refresh_market(ctx)
        ctx.open_manual("TEST", "t")
        ctx.save_state(self.state_path)
        loaded = BotContext.load(self.state_path)
        self.assertEqual(len(loaded.rm.open_positions), 1)
        self.assertAlmostEqual(loaded.rm.balance_usdt, ctx.rm.balance_usdt)


class TelegramTests(unittest.TestCase):
    def test_old_backlog_ignored_and_bot_suffix(self):
        tg = TelegramController()
        tg.token, tg.chat_id = "x", "42"
        old = {"update_id": 1, "message": {"date": int(tg.started_at) - 3600, "chat": {"id": 42}, "text": "/buy"}}
        new = {"update_id": 2, "message": {"date": int(tg.started_at) + 1, "chat": {"id": 42}, "text": "/status@MyBot"}}
        with mock.patch.object(tg, "_api", return_value={"result": [old, new]}):
            fresh = tg.fetch_updates()
        self.assertEqual([u["update_id"] for u in fresh], [2])
        self.assertEqual(tg.last_update_id, 2)
        ctx = BotContext(RiskManager())
        sent = []
        with mock.patch.object(tg, "send_message", side_effect=sent.append):
            tg.handle_updates(fresh, ctx, "t")
        self.assertTrue(sent and "PORTFEL" in sent[0])

    def test_close_without_argument_does_not_close_everything(self):
        tg = TelegramController()
        tg.chat_id = "42"
        ctx = BotContext(RiskManager())
        ctx.update_market("PAXGUSDT", parsed([2000.0] * 60, forming=False), 2000.0, {})
        ctx.open_manual("TEST", "t")
        with mock.patch.object(tg, "send_message"):
            tg._handle_command("/close", ctx, "t")
        self.assertEqual(len(ctx.rm.open_positions), 1)


class WebDashboardTests(unittest.TestCase):
    def test_token_required(self):
        import web_dashboard
        ctx = BotContext(RiskManager())
        with mock.patch.object(config, "WEB_DASHBOARD_TOKEN", "secret"), \
                mock.patch.object(config, "WEB_HOST", "127.0.0.1"), \
                mock.patch.object(config, "WEB_PORT", 0):
            server = web_dashboard.start_web_dashboard(ctx)
        port = server.server_address[1]
        try:
            base = f"http://127.0.0.1:{port}"
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(f"{base}/api/state", timeout=5)
            self.assertEqual(cm.exception.code, 401)

            req = urllib.request.Request(
                f"{base}/api/action", data=b'{"action":"toggle_pause"}',
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(cm.exception.code, 401)
            self.assertFalse(ctx.rm.auto_trading_paused)

            req = urllib.request.Request(
                f"{base}/api/action", data=b'{"action":"toggle_pause"}',
                headers={"Content-Type": "application/json", "X-Auth-Token": "secret"},
            )
            with mock.patch.object(ctx, "save_state"):
                body = json.loads(urllib.request.urlopen(req, timeout=5).read())
            self.assertTrue(body["ok"])
            self.assertTrue(ctx.rm.auto_trading_paused)

            req = urllib.request.Request(
                f"{base}/api/action", data=b"not json",
                headers={"Content-Type": "application/json", "X-Auth-Token": "secret"},
            )
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(cm.exception.code, 400)

            state = json.loads(urllib.request.urlopen(
                urllib.request.Request(f"{base}/api/state", headers={"X-Auth-Token": "secret"}), timeout=5).read())
            self.assertEqual(state["symbol"], config.SYMBOL)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
