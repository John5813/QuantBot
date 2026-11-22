"""
Yengil Veb-Sayt Boshqaruv Paneli (Web Dashboard + API).
Python standart `http.server` kutubxonasida yozilgan — VPS'da qo'shimcha RAM egallamaydi!
Brauzerda yoki Telegram WebApp (Mini App) ichida ochiladi: http://<VPS_IP>:8080
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
import urllib.parse
from datetime import datetime
import config


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="uz">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Quant Spot Bot — Veb Boshqaruv Paneli</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-4 md:p-6">
  <div class="max-w-5xl mx-auto space-y-5">
    <!-- Header -->
    <div class="flex flex-wrap items-center justify-between gap-4 bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div>
        <h1 class="text-lg font-bold text-white flex items-center gap-2">
          📊 Quant Spot Bot — Veb Boshqaruv Paneli
          <span id="badgeMode" class="text-xs px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 border border-sky-500/30">VIRTUAL SINOV</span>
        </h1>
        <p class="text-xs text-slate-400 mt-0.5">Telegram bot bilan 100% sinxron ishlaydi • 1% Risk • 3% Kunlik Kill-Switch</p>
      </div>
      <div class="flex items-center gap-2">
        <button onclick="sendAction('add_trade')" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition">
          ➕ Yangi / 2-Bitim Qo'shish
        </button>
        <button onclick="sendAction('close_all')" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white transition">
          ❌ Barchasini Yopish
        </button>
        <button onclick="sendAction('toggle_pause')" id="btnPause" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 transition">
          ⏸ Pauza
        </button>
      </div>
    </div>

    <!-- Market / Asset Selector Card -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-sm font-semibold text-white">🎯 Bozor va Aktivni Tanlash</h2>
          <p class="text-xs text-slate-400">Bot faqat siz tanlagan bozorda ishlaydi yoki ruxsat bersangiz 5 ta bozorni avto-skaner qiladi</p>
        </div>
        <label class="flex items-center gap-2 text-xs bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700 cursor-pointer">
          <input type="checkbox" id="chkAutoScan" onchange="toggleAutoScan(this.checked)" class="accent-sky-500" />
          <span>🔍 Avto-Skaner (5 ta bozordan eng qulayini tanlash)</span>
        </label>
      </div>
      <div id="assetButtons" class="grid grid-cols-2 sm:grid-cols-5 gap-2 pt-1"></div>
    </div>

    <!-- KPI Cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
        <div class="text-xs text-slate-400">Umumiy Spot Balans</div>
        <div id="kpiBalanceUzs" class="text-base font-bold text-white mt-1">1,000,000 so'm</div>
        <div id="kpiBalanceUsdt" class="text-xs text-slate-400 font-mono">$78.12 USDT</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
        <div class="text-xs text-slate-400">Bugungi Natija (Kunlik Limit: -3%)</div>
        <div id="kpiDailyPnl" class="text-base font-bold text-emerald-400 mt-1">+0 so'm</div>
        <div id="kpiKillSwitch" class="text-xs text-emerald-400">🟢 Kill-Switch: Xavfsiz</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
        <div class="text-xs text-slate-400">Ochiq Bitimlar</div>
        <div id="kpiOpenCount" class="text-base font-bold text-white mt-1">0 / 2</div>
        <div id="kpiFreeCap" class="text-xs text-slate-400 font-mono">Bo'sh: $78.12</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
        <div class="text-xs text-slate-400">Tanlangan Bozor Narxi</div>
        <div id="kpiPrice" class="text-base font-bold text-sky-400 mt-1">$2,650.00</div>
        <div id="kpiIndicators" class="text-xs text-slate-400 font-mono">RSI: 50.0 | EMA20/50</div>
      </div>
    </div>

    <!-- Live Chart Canvas -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
      <div class="flex items-center justify-between text-xs">
        <span id="chartTitle" class="font-semibold text-white">📈 Jonli Shamchalar va Strategiya Chiziqlari (PAXGUSDT • 15m)</span>
        <div class="flex items-center gap-3 font-mono text-[11px] text-slate-400">
          <span><b class="text-sky-400">━━</b> EMA 20</span>
          <span><b class="text-amber-400">━━</b> EMA 50</span>
          <span><b class="text-emerald-400">- -</b> Take-Profit (+2%)</span>
          <span><b class="text-rose-400">- -</b> Stop-Loss (-1%)</span>
        </div>
      </div>
      <canvas id="liveChart" class="w-full rounded-lg bg-slate-950 border border-slate-800" height="260"></canvas>
    </div>

    <!-- Active Positions & Past Trades History -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
        <h3 class="text-sm font-semibold text-white">⚡ Hozirgi Ochiq Bitimlar (#1 va #2)</h3>
        <div id="openPositionsList" class="text-xs text-slate-400 space-y-2">Hozir ochiq bitim yo'q.</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
        <h3 class="text-sm font-semibold text-white">📜 O'tmishdagi Bitimlar Tarixi</h3>
        <div id="historyList" class="text-xs text-slate-400 space-y-1.5 max-h-48 overflow-y-auto">Hali yopilgan bitimlar yo'q.</div>
      </div>
    </div>
  </div>

  <script>
    let latestState = null;

    async function fetchState() {
      try {
        const res = await fetch('/api/state');
        latestState = await res.json();
        renderState(latestState);
      } catch (e) {}
    }

    async function sendAction(action, extra = {}) {
      await fetch('/api/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ...extra })
      });
      await fetchState();
    }

    function selectSymbol(sym) {
      sendAction('set_symbol', { symbol: sym });
    }

    function toggleAutoScan(enabled) {
      sendAction('set_autoscan', { enabled });
    }

    function renderState(st) {
      document.getElementById('chkAutoScan').checked = !!st.auto_scan_markets;
      document.getElementById('btnPause').textContent = st.auto_trading_paused ? '▶️ Davom ettirish' : '⏸ Pauza';

      // Render asset selector buttons
      const btnContainer = document.getElementById('assetButtons');
      btnContainer.innerHTML = '';
      Object.entries(st.allowed_symbols || {}).forEach(([sym, label]) => {
        const active = sym === st.symbol;
        const btn = document.createElement('button');
        btn.onclick = () => selectSymbol(sym);
        btn.className = `px-3 py-2 rounded-lg text-xs font-medium border text-left transition ${
          active
            ? 'bg-sky-500/20 border-sky-500 text-white'
            : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
        }`;
        btn.innerHTML = `<div class="font-bold">${sym}</div><div class="text-[11px] opacity-80">${label}</div>`;
        btnContainer.appendChild(btn);
      });

      document.getElementById('kpiBalanceUzs').textContent = `${(st.balance_uzs || 0).toLocaleString()} so'm`;
      document.getElementById('kpiBalanceUsdt').textContent = `$${(st.balance_usdt || 0).toFixed(2)} USDT`;
      const dUzs = Math.round((st.daily_pnl_usdt || 0) * st.uzs_per_usd);
      const dEl = document.getElementById('kpiDailyPnl');
      dEl.textContent = `${dUzs >= 0 ? '+' : ''}${dUzs.toLocaleString()} so'm`;
      dEl.className = `text-base font-bold mt-1 ${dUzs >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;

      document.getElementById('kpiKillSwitch').textContent = st.kill_switch_active
        ? '🛑 Kill-Switch: Bugun savdo bloklangan!'
        : '🟢 Kill-Switch: Xavfsiz';
      document.getElementById('kpiOpenCount').textContent = `${(st.open_positions || []).length} / 2`;
      document.getElementById('kpiFreeCap').textContent = `Bo'sh: $${(st.free_capital_usdt || 0).toFixed(2)}`;
      document.getElementById('kpiPrice').textContent = `$${(st.current_price || 0).toLocaleString()}`;
      document.getElementById('kpiIndicators').textContent =
        `RSI: ${st.metrics?.rsi ?? '-'} | EMA20: ${st.metrics?.fast_ema ?? '-'}`;
      document.getElementById('chartTitle').textContent =
        `📈 Jonli Shamchalar va Strategiya Chiziqlari (${st.symbol} • ${st.timeframe})`;

      // Open positions
      const openEl = document.getElementById('openPositionsList');
      if (!st.open_positions || st.open_positions.length === 0) {
        openEl.innerHTML = '<div class="text-slate-500">Hozir ochiq bitim yo\\'q.</div>';
      } else {
        openEl.innerHTML = st.open_positions.map(p => {
          const pnlUzs = Math.round((st.current_price - p.entry_price) * p.quantity * st.uzs_per_usd);
          return `<div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between">
            <div>
              <div class="font-bold text-white">Bitim #${p.position_id} (${p.symbol} • ${p.source})</div>
              <div class="text-[11px] font-mono text-slate-400">Kirish: $${p.entry_price} | SL: $${p.stop_loss_price} | TP: $${p.take_profit_price}</div>
            </div>
            <div class="text-right">
              <div class="font-bold ${pnlUzs >= 0 ? 'text-emerald-400' : 'text-rose-400'}">${pnlUzs >= 0 ? '+' : ''}${pnlUzs.toLocaleString()} so'm</div>
              <button onclick="sendAction('close_id', {position_id: ${p.position_id}})" class="text-[11px] text-rose-400 underline">Yopish</button>
            </div>
          </div>`;
        }).join('');
      }

      // History
      const histEl = document.getElementById('historyList');
      if (!st.recent_trades || st.recent_trades.length === 0) {
        histEl.innerHTML = '<div class="text-slate-500">Hali yopilgan bitimlar yo\\'q.</div>';
      } else {
        histEl.innerHTML = st.recent_trades.slice().reverse().map(t => `
          <div class="p-2 rounded bg-slate-950 border border-slate-800 flex items-center justify-between font-mono text-[11px]">
            <span>[${t.closed_at}] #${t.position_id} ${t.symbol} (${t.reason})</span>
            <span class="${t.pnl_uzs >= 0 ? 'text-emerald-400' : 'text-rose-400'} font-bold">${t.pnl_uzs >= 0 ? '+' : ''}${t.pnl_uzs.toLocaleString()} so'm</span>
          </div>
        `).join('');
      }

      drawChart(st);
    }

    function drawChart(st) {
      const candles = st.candles || [];
      if (!candles.length) return;
      const canvas = document.getElementById('liveChart');
      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = 260 * dpr;
      ctx.save();
      ctx.scale(dpr, dpr);

      const W = rect.width, H = 260;
      ctx.clearRect(0, 0, W, H);
      const slice = candles.slice(-55);
      let minP = Infinity, maxP = -Infinity;
      slice.forEach(c => {
        if (c.low < minP) minP = c.low;
        if (c.high > maxP) maxP = c.high;
      });
      (st.open_positions || []).forEach(p => {
        if (p.stop_loss_price < minP) minP = p.stop_loss_price;
        if (p.take_profit_price > maxP) maxP = p.take_profit_price;
      });
      const pad = (maxP - minP) * 0.12 || 5;
      minP -= pad; maxP += pad;

      const chartRight = W - 65;
      const yFor = p => 14 + (1 - (p - minP) / (maxP - minP)) * (H - 28);
      const stepX = chartRight / slice.length;

      // Grid
      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.font = '10px monospace';
      for (let g = 0; g <= 4; g++) {
        const p = minP + ((maxP - minP) * (4 - g)) / 4;
        const y = yFor(p);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartRight, y); ctx.stroke();
        ctx.fillText('$' + p.toFixed(1), chartRight + 5, y + 3);
      }

      // Open positions SL/TP lines
      (st.open_positions || []).forEach(p => {
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = '#10b981';
        ctx.beginPath(); ctx.moveTo(0, yFor(p.take_profit_price)); ctx.lineTo(chartRight, yFor(p.take_profit_price)); ctx.stroke();
        ctx.strokeStyle = '#f43f5e';
        ctx.beginPath(); ctx.moveTo(0, yFor(p.stop_loss_price)); ctx.lineTo(chartRight, yFor(p.stop_loss_price)); ctx.stroke();
        ctx.setLineDash([]);
      });

      // Candles
      slice.forEach((c, i) => {
        const x = i * stepX + stepX * 0.5;
        const bull = c.close >= c.open;
        ctx.strokeStyle = bull ? '#10b981' : '#f43f5e';
        ctx.fillStyle = bull ? '#10b981' : '#f43f5e';
        ctx.beginPath(); ctx.moveTo(x, yFor(c.high)); ctx.lineTo(x, yFor(c.low)); ctx.stroke();
        const yO = yFor(c.open), yC = yFor(c.close);
        ctx.fillRect(x - Math.max(2, stepX * 0.28), Math.min(yO, yC), Math.max(4, stepX * 0.56), Math.max(2, Math.abs(yC - yO)));
      });

      ctx.restore();
    }

    fetchState();
    setInterval(fetchState, 3000);
  </script>
</body>
</html>
"""


class BotWebContext:
    """Bot va Veb-Sayt o'rtasidagi jonli umumiy xotira."""
    def __init__(self, rm) -> None:
        self.rm = rm
        self.candles: list[dict] = []
        self.current_price: float = 2650.0
        self.metrics: dict = {}


def start_web_dashboard(ctx: BotWebContext) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Terminalni ortiqcha loglar bilan to'ldirmaslik uchun

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/index"):
                body = DASHBOARD_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/api/state"):
                state = {
                    "symbol": config.SYMBOL,
                    "timeframe": config.TIMEFRAME,
                    "allowed_symbols": config.ALLOWED_SYMBOLS,
                    "auto_scan_markets": config.AUTO_SCAN_MARKETS,
                    "auto_trading_paused": ctx.rm.auto_trading_paused,
                    "uzs_per_usd": config.UZS_PER_USD,
                    "balance_usdt": ctx.rm.balance_usdt,
                    "balance_uzs": round(ctx.rm.balance_usdt * config.UZS_PER_USD, 0),
                    "free_capital_usdt": ctx.rm.free_capital_usdt,
                    "daily_pnl_usdt": ctx.rm.daily_realized_pnl_usdt,
                    "kill_switch_active": ctx.rm.kill_switch_active,
                    "current_price": ctx.current_price,
                    "metrics": ctx.metrics,
                    "open_positions": [p.__dict__ for p in ctx.rm.open_positions],
                    "recent_trades": ctx.rm.history[-25:],
                    "candles": ctx.candles[-60:],
                }
                body = json.dumps(state, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path.startswith("/api/action"):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                action = payload.get("action")
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if action == "set_symbol":
                    sym = payload.get("symbol", "")
                    if sym in config.ALLOWED_SYMBOLS:
                        config.SYMBOL = sym
                        config.AUTO_SCAN_MARKETS = False
                elif action == "set_autoscan":
                    config.AUTO_SCAN_MARKETS = bool(payload.get("enabled", False))
                elif action == "toggle_pause":
                    ctx.rm.auto_trading_paused = not ctx.rm.auto_trading_paused
                elif action == "add_trade":
                    allowed, _ = ctx.rm.can_open_trade(is_manual_add=True)
                    if allowed and ctx.current_price > 0:
                        ctx.rm.open_new_position(ctx.current_price, now_str, source="WEB_MANUAL")
                elif action == "close_all":
                    for p in list(ctx.rm.open_positions):
                        ctx.rm.close_position_by_id(p.position_id, ctx.current_price, "WEB_CLOSE", now_str)
                elif action == "close_id":
                    pid = int(payload.get("position_id", 0))
                    try:
                        ctx.rm.close_position_by_id(pid, ctx.current_price, "WEB_CLOSE", now_str)
                    except Exception:
                        pass

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

    server = HTTPServer((config.WEB_HOST, config.WEB_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"🌐 Veb-Sayt Boshqaruv Paneli ishga tushdi: http://localhost:{config.WEB_PORT}")
