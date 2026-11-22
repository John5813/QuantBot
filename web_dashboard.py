"""
Yengil Veb-Sayt Boshqaruv Paneli (Web Dashboard + API).
Python standart `http.server` kutubxonasida yozilgan — VPS'da qo'shimcha RAM egallamaydi.

XAVFSIZLIK:
- Standart holatda faqat 127.0.0.1 da ochiladi (SSH tunnel orqali kiring:
  `ssh -L 8080:127.0.0.1:8080 root@<VPS_IP>`, keyin brauzerda http://localhost:8080).
- Internetga ochish uchun (`WEB_HOST=0.0.0.0`) `WEB_DASHBOARD_TOKEN` majburiy.
  Shunda panel manzili: http://<VPS_IP>:8080/?token=<TOKEN>
  Tokensiz hech kim bitim ochib/yopa olmaydi.
"""

import hmac
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
import config
from bot_context import BotContext

MAX_BODY_BYTES = 10_000

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="uz">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="referrer" content="no-referrer" />
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
        <p class="text-xs text-slate-400 mt-0.5">Telegram bot bilan sinxron ishlaydi • 1% Risk • 3% Kunlik Kill-Switch</p>
      </div>
      <div class="flex items-center gap-2">
        <button onclick="sendAction('add_trade')" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition">
          ➕ Yangi / 2-Bitim Qo'shish
        </button>
        <button onclick="confirmCloseAll()" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white transition">
          ❌ Barchasini Yopish
        </button>
        <button onclick="sendAction('toggle_pause')" id="btnPause" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 transition">
          ⏸ Pauza
        </button>
      </div>
    </div>

    <div id="notice" class="hidden text-xs rounded-lg px-3 py-2 border"></div>

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
        <div id="kpiBalanceUzs" class="text-base font-bold text-white mt-1">—</div>
        <div id="kpiBalanceUsdt" class="text-xs text-slate-400 font-mono">—</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
        <div class="text-xs text-slate-400">Bugungi Natija (Kunlik Limit: -3%)</div>
        <div id="kpiDailyPnl" class="text-base font-bold text-emerald-400 mt-1">—</div>
        <div id="kpiKillSwitch" class="text-xs text-emerald-400">—</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
        <div class="text-xs text-slate-400">Ochiq Bitimlar</div>
        <div id="kpiOpenCount" class="text-base font-bold text-white mt-1">—</div>
        <div id="kpiFreeCap" class="text-xs text-slate-400 font-mono">—</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
        <div class="text-xs text-slate-400">Tanlangan Bozor Narxi</div>
        <div id="kpiPrice" class="text-base font-bold text-sky-400 mt-1">yuklanmoqda...</div>
        <div id="kpiIndicators" class="text-xs text-slate-400 font-mono">RSI: - | EMA20: -</div>
      </div>
    </div>

    <!-- Live Chart Canvas -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span id="chartTitle" class="font-semibold text-white">📈 Yopilgan Shamchalar va Strategiya Chiziqlari</span>
        <div class="flex items-center gap-3 font-mono text-[11px] text-slate-400">
          <span><b class="text-sky-400">━━</b> EMA 20</span>
          <span><b class="text-amber-400">━━</b> EMA 50</span>
          <span><b class="text-emerald-400">- -</b> <span id="legendTp">Take-Profit</span></span>
          <span><b class="text-rose-400">- -</b> <span id="legendSl">Stop-Loss</span></span>
        </div>
      </div>
      <canvas id="liveChart" class="w-full rounded-lg bg-slate-950 border border-slate-800" height="260"></canvas>
    </div>

    <!-- Active Positions & Past Trades History -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
        <h3 class="text-sm font-semibold text-white">⚡ Hozirgi Ochiq Bitimlar</h3>
        <div id="openPositionsList" class="text-xs text-slate-400 space-y-2">Hozir ochiq bitim yo'q.</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
        <h3 class="text-sm font-semibold text-white">📜 O'tmishdagi Bitimlar Tarixi</h3>
        <div id="historyList" class="text-xs text-slate-400 space-y-1.5 max-h-48 overflow-y-auto">Hali yopilgan bitimlar yo'q.</div>
      </div>
    </div>
  </div>

  <script>
    const TOKEN = new URLSearchParams(location.search).get('token') || '';
    let latestState = null;

    function esc(v) {
      return String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }
    function fmtUsd(v) {
      if (v === null || v === undefined) return '-';
      return '$' + Number(v).toLocaleString(undefined, {maximumFractionDigits: v >= 1 ? 2 : 6});
    }

    function showNotice(text, ok) {
      const el = document.getElementById('notice');
      el.textContent = text;
      el.className = 'text-xs rounded-lg px-3 py-2 border ' +
        (ok ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-rose-500/10 border-rose-500/30 text-rose-300');
      clearTimeout(showNotice._t);
      showNotice._t = setTimeout(() => el.classList.add('hidden'), 6000);
    }

    async function api(path, options = {}) {
      options.headers = Object.assign({'X-Auth-Token': TOKEN}, options.headers || {});
      const res = await fetch(path, options);
      if (res.status === 401) throw new Error("Ruxsat yo'q: manzilga ?token=... qo'shing");
      return res.json();
    }

    async function fetchState() {
      try {
        latestState = await api('/api/state');
        renderState(latestState);
      } catch (e) {
        showNotice(e.message || "Bot bilan aloqa yo'q", false);
      }
    }

    async function sendAction(action, extra = {}) {
      try {
        const r = await api('/api/action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, ...extra })
        });
        if (r.message) showNotice(r.message, r.ok);
      } catch (e) {
        showNotice(e.message || 'Xato', false);
      }
      await fetchState();
    }

    function confirmCloseAll() {
      if (confirm("Barcha ochiq bitimlarni hozirgi narxda yopasizmi?")) sendAction('close_all');
    }

    function toggleAutoScan(enabled) {
      sendAction('set_autoscan', { enabled });
    }

    function renderState(st) {
      const live = st.mode === 'LIVE';
      const badge = document.getElementById('badgeMode');
      badge.textContent = live ? 'JONLI SAVDO' : 'VIRTUAL SINOV';
      document.getElementById('chkAutoScan').checked = !!st.auto_scan_markets;
      document.getElementById('btnPause').textContent = st.auto_trading_paused ? '▶️ Davom ettirish' : '⏸ Pauza';
      document.getElementById('legendTp').textContent = `Take-Profit (+${st.tp_pct.toFixed(2)}%)`;
      document.getElementById('legendSl').textContent = `Stop-Loss (-${st.stop_pct.toFixed(2)}%)`;

      const btnContainer = document.getElementById('assetButtons');
      btnContainer.innerHTML = '';
      Object.entries(st.allowed_symbols || {}).forEach(([sym, label]) => {
        const active = sym === st.symbol;
        const btn = document.createElement('button');
        btn.onclick = () => sendAction('set_symbol', { symbol: sym });
        btn.className = `px-3 py-2 rounded-lg text-xs font-medium border text-left transition ${
          active
            ? 'bg-sky-500/20 border-sky-500 text-white'
            : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
        }`;
        btn.innerHTML = `<div class="font-bold">${esc(sym)}</div><div class="text-[11px] opacity-80">${esc(label)}</div>`;
        btnContainer.appendChild(btn);
      });

      document.getElementById('kpiBalanceUzs').textContent = `${(st.balance_uzs || 0).toLocaleString()} so'm`;
      document.getElementById('kpiBalanceUsdt').textContent = `$${(st.balance_usdt || 0).toFixed(2)} USDT`;
      const dUzs = Math.round((st.daily_pnl_usdt || 0) * st.uzs_per_usd);
      const dEl = document.getElementById('kpiDailyPnl');
      dEl.textContent = `${dUzs >= 0 ? '+' : ''}${dUzs.toLocaleString()} so'm`;
      dEl.className = `text-base font-bold mt-1 ${dUzs >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;

      const ks = document.getElementById('kpiKillSwitch');
      ks.textContent = st.kill_switch_active ? '🛑 Kill-Switch: Bugun savdo bloklangan!' : '🟢 Kill-Switch: Xavfsiz';
      ks.className = `text-xs ${st.kill_switch_active ? 'text-rose-400' : 'text-emerald-400'}`;
      document.getElementById('kpiOpenCount').textContent = `${(st.open_positions || []).length} / ${st.max_positions}`;
      document.getElementById('kpiFreeCap').textContent = `Bo'sh: $${(st.free_capital_usdt || 0).toFixed(2)}`;
      const stale = st.price_age_sec === null || st.price_age_sec > 120;
      document.getElementById('kpiPrice').textContent = st.current_price ? fmtUsd(st.current_price) + (stale ? ' (eski)' : '') : 'yuklanmoqda...';
      document.getElementById('kpiIndicators').textContent =
        `RSI: ${st.metrics?.rsi ?? '-'} | EMA20: ${st.metrics?.fast_ema ?? '-'}`;
      document.getElementById('chartTitle').textContent =
        `📈 Yopilgan Shamchalar va Strategiya Chiziqlari (${st.symbol} • ${st.timeframe})`;

      const openEl = document.getElementById('openPositionsList');
      if (!st.open_positions || st.open_positions.length === 0) {
        openEl.innerHTML = `<div class="text-slate-500">Hozir ochiq bitim yo'q.</div>`;
      } else {
        openEl.innerHTML = st.open_positions.map(p => {
          const px = (st.prices || {})[p.symbol];
          const pnlUzs = px ? Math.round((px - p.entry_price) * p.quantity * st.uzs_per_usd) : null;
          const pnlHtml = pnlUzs === null
            ? '<span class="text-slate-500">narx yo’q</span>'
            : `<span class="${pnlUzs >= 0 ? 'text-emerald-400' : 'text-rose-400'}">${pnlUzs >= 0 ? '+' : ''}${pnlUzs.toLocaleString()} so'm</span>`;
          return `<div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between">
            <div>
              <div class="font-bold text-white">Bitim #${Number(p.position_id)} (${esc(p.symbol)} • ${esc(p.source)})</div>
              <div class="text-[11px] font-mono text-slate-400">Kirish: ${fmtUsd(p.entry_price)} | SL: ${fmtUsd(p.stop_loss_price)} | TP: ${fmtUsd(p.take_profit_price)}</div>
            </div>
            <div class="text-right">
              <div class="font-bold">${pnlHtml}</div>
              <button onclick="sendAction('close_id', {position_id: ${Number(p.position_id)}})" class="text-[11px] text-rose-400 underline">Yopish</button>
            </div>
          </div>`;
        }).join('');
      }

      const histEl = document.getElementById('historyList');
      if (!st.recent_trades || st.recent_trades.length === 0) {
        histEl.innerHTML = `<div class="text-slate-500">Hali yopilgan bitimlar yo'q.</div>`;
      } else {
        histEl.innerHTML = st.recent_trades.slice().reverse().map(t => `
          <div class="p-2 rounded bg-slate-950 border border-slate-800 flex items-center justify-between font-mono text-[11px]">
            <span>[${esc(t.closed_at)}] #${Number(t.position_id)} ${esc(t.symbol)} (${esc(t.reason)})</span>
            <span class="${t.pnl_uzs >= 0 ? 'text-emerald-400' : 'text-rose-400'} font-bold">${t.pnl_uzs >= 0 ? '+' : ''}${Number(t.pnl_uzs).toLocaleString()} so'm</span>
          </div>
        `).join('');
      }

      drawChart(st);
    }

    function drawChart(st) {
      if (!st) return;
      const candles = st.candles || [];
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
      if (!candles.length) { ctx.restore(); return; }

      const n = Math.min(55, candles.length);
      const slice = candles.slice(-n);
      const emaF = (st.ema_fast || []).slice(-n);
      const emaS = (st.ema_slow || []).slice(-n);
      const positions = (st.open_positions || []).filter(p => p.symbol === st.symbol);
      let minP = Infinity, maxP = -Infinity;
      slice.forEach(c => { minP = Math.min(minP, c.low); maxP = Math.max(maxP, c.high); });
      positions.forEach(p => { minP = Math.min(minP, p.stop_loss_price); maxP = Math.max(maxP, p.take_profit_price); });
      const pad = (maxP - minP) * 0.12 || maxP * 0.002 || 1;
      minP -= pad; maxP += pad;

      const chartRight = W - 70;
      const yFor = p => 14 + (1 - (p - minP) / (maxP - minP)) * (H - 28);
      const stepX = chartRight / slice.length;
      const xFor = i => i * stepX + stepX * 0.5;
      const digits = maxP >= 1000 ? 1 : maxP >= 1 ? 3 : 6;

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.font = '10px monospace';
      for (let g = 0; g <= 4; g++) {
        const p = minP + ((maxP - minP) * (4 - g)) / 4;
        const y = yFor(p);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartRight, y); ctx.stroke();
        ctx.fillText('$' + p.toFixed(digits), chartRight + 5, y + 3);
      }

      positions.forEach(p => {
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = '#10b981';
        ctx.beginPath(); ctx.moveTo(0, yFor(p.take_profit_price)); ctx.lineTo(chartRight, yFor(p.take_profit_price)); ctx.stroke();
        ctx.strokeStyle = '#f43f5e';
        ctx.beginPath(); ctx.moveTo(0, yFor(p.stop_loss_price)); ctx.lineTo(chartRight, yFor(p.stop_loss_price)); ctx.stroke();
        ctx.setLineDash([]);
      });

      slice.forEach((c, i) => {
        const x = xFor(i);
        const bull = c.close >= c.open;
        ctx.strokeStyle = bull ? '#10b981' : '#f43f5e';
        ctx.fillStyle = bull ? '#10b981' : '#f43f5e';
        ctx.beginPath(); ctx.moveTo(x, yFor(c.high)); ctx.lineTo(x, yFor(c.low)); ctx.stroke();
        const yO = yFor(c.open), yC = yFor(c.close);
        ctx.fillRect(x - Math.max(2, stepX * 0.28), Math.min(yO, yC), Math.max(4, stepX * 0.56), Math.max(2, Math.abs(yC - yO)));
      });

      [[emaS, '#fbbf24'], [emaF, '#38bdf8']].forEach(([series, color]) => {
        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.beginPath();
        let started = false;
        series.forEach((v, i) => {
          if (v === null || v === undefined) return;
          if (!started) { ctx.moveTo(xFor(i), yFor(v)); started = true; } else ctx.lineTo(xFor(i), yFor(v));
        });
        ctx.stroke();
      });

      ctx.restore();
    }

    fetchState();
    setInterval(fetchState, 3000);
    window.addEventListener('resize', () => drawChart(latestState));
  </script>
</body>
</html>
"""


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def start_web_dashboard(ctx: BotContext) -> Optional[ThreadingHTTPServer]:
    host = config.WEB_HOST
    token = config.WEB_DASHBOARD_TOKEN
    if not _is_loopback(host) and not token:
        print(
            "⚠️ [Veb-Panel] WEB_HOST tashqi tarmoqqa ochiq, lekin WEB_DASHBOARD_TOKEN o'rnatilmagan!\n"
            "   Begona odam bitim ochib/yopmasligi uchun panel faqat 127.0.0.1 da ishga tushiriladi."
        )
        host = "127.0.0.1"

    class Handler(BaseHTTPRequestHandler):
        server_version = "QuantBot"
        sys_version = ""

        def log_message(self, format, *args):  # noqa: A002
            pass  # Terminalni ortiqcha loglar bilan to'ldirmaslik uchun

        # ---------------------------------------------------------- yordamchilar

        def _authorized(self) -> bool:
            if not token:
                return True
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            supplied = self.headers.get("X-Auth-Token") or (query.get("token") or [""])[0]
            return hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8"))

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")

        # ---------------------------------------------------------- GET

        def do_GET(self):  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index", "/index.html"):
                if not self._authorized():
                    self._send(401, "Ruxsat yo'q. Manzilga ?token=... qo'shing.".encode("utf-8"),
                               "text/plain; charset=utf-8")
                    return
                self._send(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/state":
                if not self._authorized():
                    self._json(401, {"ok": False, "message": "Ruxsat yo'q"})
                    return
                self._json(200, ctx.snapshot())
            else:
                self._send(404, b"Not found", "text/plain")

        # ---------------------------------------------------------- POST

        def do_POST(self):  # noqa: N802
            if urllib.parse.urlparse(self.path).path != "/api/action":
                self._send(404, b"Not found", "text/plain")
                return
            # Faqat header orqali token qabul qilinadi (CSRF'dan himoya: begona sayt bu headerni yubora olmaydi)
            if token and not hmac.compare_digest(
                (self.headers.get("X-Auth-Token") or "").encode("utf-8"), token.encode("utf-8")
            ):
                self._json(401, {"ok": False, "message": "Ruxsat yo'q"})
                return
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                self._json(415, {"ok": False, "message": "Content-Type: application/json bo'lishi kerak"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_BODY_BYTES:
                    raise ValueError("so'rov hajmi noto'g'ri")
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("JSON obyekt kutilgan")
            except (ValueError, UnicodeDecodeError) as exc:
                self._json(400, {"ok": False, "message": f"Noto'g'ri so'rov: {exc}"})
                return

            ok, message = self._handle_action(payload)
            if ok:
                try:
                    ctx.save_state()
                except OSError as exc:
                    print(f"[Holat] Saqlashda xato: {exc}")
            self._json(200, {"ok": ok, "message": message})

        def _handle_action(self, payload: dict) -> tuple[bool, str]:
            action = payload.get("action")
            now_str = config.local_now().strftime("%Y-%m-%d %H:%M:%S")
            rm = ctx.rm

            if action == "set_symbol":
                sym = str(payload.get("symbol", ""))
                if ctx.set_symbol(sym):
                    return True, f"{sym} tanlandi (Avto-Skaner o'chirildi)."
                return False, "Bu aktivga ruxsat berilmagan."

            if action == "set_autoscan":
                with ctx.lock:
                    config.AUTO_SCAN_MARKETS = bool(payload.get("enabled", False))
                return True, "Avto-Skaner " + ("yoqildi." if config.AUTO_SCAN_MARKETS else "o'chirildi.")

            if action == "toggle_pause":
                with ctx.lock:
                    rm.auto_trading_paused = not rm.auto_trading_paused
                    paused = rm.auto_trading_paused
                return True, "Avto-savdo pauza qilindi." if paused else "Avto-savdo qayta yoqildi."

            if action == "add_trade":
                ok, reason, pos = ctx.open_manual("WEB_MANUAL", now_str)
                if ok and pos is not None:
                    return True, f"Bitim #{pos.position_id} ochildi: {pos.symbol} @ ${pos.entry_price:,.4f}"
                return False, f"Rad etildi: {reason}"

            if action == "close_all":
                records, errors = ctx.close_all("WEB_CLOSE", now_str)
                if errors:
                    return bool(records), f"{len(records)} ta yopildi. Xatolar: " + "; ".join(errors)
                if not records:
                    return False, "Ochiq bitim yo'q."
                total = sum(r["pnl_uzs"] for r in records)
                return True, f"{len(records)} ta bitim yopildi. Natija: {total:+,.0f} so'm"

            if action == "close_id":
                try:
                    pid = int(payload.get("position_id", 0))
                    rec = ctx.close_one(pid, "WEB_CLOSE", now_str)
                except (TypeError, ValueError) as exc:
                    return False, str(exc)
                return True, f"Bitim #{pid} yopildi. Natija: {rec['pnl_uzs']:+,.0f} so'm"

            return False, "Noma'lum amal."

    server = ThreadingHTTPServer((host, config.WEB_PORT), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="web-dashboard")
    thread.start()
    shown_host = "localhost" if _is_loopback(host) else host
    suffix = "/?token=<WEB_DASHBOARD_TOKEN>" if token else ""
    print(f"🌐 Veb-Sayt Boshqaruv Paneli ishga tushdi: http://{shown_host}:{server.server_address[1]}{suffix}")
    return server
