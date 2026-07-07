/* ============================================================
   PRIVACY / CONFIG UNLOCK SYSTEM
   ============================================================ */
const UNLOCK = {
  correctHash: "d6e1ba5ffc9cedb66266c42cc04a2f03eb794e11ac4e3e2f55e1f4f9779e3fc7",
  logoClicks: 0,
  themeClicks: 0,
  submitClicksEmpty: 0,
  stage: 0,
  resetTimer: null,
  unlocked: sessionStorage.getItem("jg-config-unlocked") === "1",
};

async function sha256(text) {
  if (window.crypto && window.crypto.subtle) {
    try {
      const buf = new TextEncoder().encode(text);
      const hash = await crypto.subtle.digest("SHA-256", buf);
      return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, "0")).join("");
    } catch (e) {}
  }
  return sha256JS(text);
}

function sha256JS(msg) {
  function rr(n, x) { return (x >>> n) | (x << (32 - n)); }
  function toHex(n) {
    let s = "", v;
    for (let i = 7; i >= 0; i--) {
      v = (n >>> (i * 4)) & 0x0f;
      s += v.toString(16);
    }
    return s;
  }
  const K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  const H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const bytes = new TextEncoder().encode(msg);
  const bitLen = bytes.length * 8;
  const withPad = new Uint8Array(Math.ceil((bytes.length + 9) / 64) * 64);
  withPad.set(bytes);
  withPad[bytes.length] = 0x80;
  const dv = new DataView(withPad.buffer);
  dv.setUint32(withPad.length - 4, bitLen);
  const w = new Array(64);
  for (let chunk = 0; chunk < withPad.length; chunk += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(chunk + i * 4);
    for (let i = 16; i < 64; i++) {
      const s0 = rr(7, w[i-15]) ^ rr(18, w[i-15]) ^ (w[i-15] >>> 3);
      const s1 = rr(17, w[i-2]) ^ rr(19, w[i-2]) ^ (w[i-2] >>> 10);
      w[i] = (w[i-16] + s0 + w[i-7] + s1) | 0;
    }
    let [a,b,c,d,e,f,g,h] = H;
    for (let i = 0; i < 64; i++) {
      const S1 = rr(6,e) ^ rr(11,e) ^ rr(25,e);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[i] + w[i]) | 0;
      const S0 = rr(2,a) ^ rr(13,a) ^ rr(22,a);
      const mj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + mj) | 0;
      h = g; g = f; f = e; e = (d + t1) | 0;
      d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    H[0]=(H[0]+a)|0; H[1]=(H[1]+b)|0; H[2]=(H[2]+c)|0; H[3]=(H[3]+d)|0;
    H[4]=(H[4]+e)|0; H[5]=(H[5]+f)|0; H[6]=(H[6]+g)|0; H[7]=(H[7]+h)|0;
  }
  return H.map(toHex).join("");
}

function resetUnlockSequence() {
  UNLOCK.logoClicks = 0;
  UNLOCK.themeClicks = 0;
  UNLOCK.submitClicksEmpty = 0;
  UNLOCK.stage = 0;
  clearTimeout(UNLOCK.resetTimer);
  document.getElementById("unlock-modal")?.remove();
}

function armResetTimer() {
  clearTimeout(UNLOCK.resetTimer);
  UNLOCK.resetTimer = setTimeout(() => {
    if (UNLOCK.stage > 0 && UNLOCK.stage < 5) resetUnlockSequence();
  }, 8000);
}

function hideConfigNav() {
  if (UNLOCK.unlocked) return;
  document.querySelectorAll('[data-route="config"]').forEach(el => el.style.display = "none");
}

function revealConfigNav() {
  document.querySelectorAll('[data-route="config"]').forEach(el => el.style.display = "");
}

function showUnlockModal() {
  document.getElementById("unlock-modal")?.remove();
  const modal = document.createElement("div");
  modal.id = "unlock-modal";
  modal.className = "unlock-modal-overlay";
  modal.innerHTML = `
    <div class="unlock-modal-box">
      <div class="unlock-modal-title" id="unlock-modal-title">Access verification</div>
      <div class="unlock-modal-subtitle" id="unlock-modal-subtitle">Enter password to unlock advanced settings</div>
      <input type="password" class="unlock-modal-input" id="unlock-modal-input" placeholder="••••••••" autocomplete="off" spellcheck="false">
      <div class="unlock-modal-actions">
        <button class="btn" id="unlock-modal-cancel">Cancel</button>
        <button class="btn primary" id="unlock-modal-submit">Submit</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  setTimeout(() => modal.classList.add("open"), 10);
  const input = document.getElementById("unlock-modal-input");
  const submitBtn = document.getElementById("unlock-modal-submit");
  const cancelBtn = document.getElementById("unlock-modal-cancel");
  setTimeout(() => input?.focus(), 100);
  submitBtn.addEventListener("click", async () => {
    const val = input.value;
    armResetTimer();
    if (UNLOCK.stage === 3) {
      if (val === "") {
        UNLOCK.submitClicksEmpty++;
        if (UNLOCK.submitClicksEmpty >= 3) {
          UNLOCK.stage = 4;
          document.getElementById("unlock-modal-title").textContent = "🎉 Congrats!";
          document.getElementById("unlock-modal-subtitle").textContent = "You unlocked it. Enter the real password.";
          input.value = ""; input.placeholder = "real password"; input.focus();
        }
      } else {
        resetUnlockSequence(); modal.remove();
      }
      return;
    }
    if (UNLOCK.stage === 4) {
      if (!val) { toast("Password required", "error", 2000); return; }
      const hash = await sha256(val);
      if (hash === UNLOCK.correctHash) {
        UNLOCK.stage = 5; UNLOCK.unlocked = true;
        sessionStorage.setItem("jg-config-unlocked", "1");
        revealConfigNav(); modal.remove();
        toast("✅ Config unlocked", "success");
      } else {
        input.value = ""; toast("Access denied", "error", 2000);
        setTimeout(() => { resetUnlockSequence(); modal.remove(); }, 800);
      }
    }
  });
  cancelBtn.addEventListener("click", () => { resetUnlockSequence(); modal.remove(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitBtn.click();
    if (e.key === "Escape") cancelBtn.click();
  });
}

function initUnlockPattern() {
  if (UNLOCK.unlocked) { revealConfigNav(); return; }
  hideConfigNav();
  const brand = document.querySelector(".brand");
  if (brand) {
    brand.addEventListener("click", () => {
      armResetTimer();
      if (UNLOCK.stage === 0) {
        UNLOCK.logoClicks++;
        if (UNLOCK.logoClicks >= 4) { UNLOCK.stage = 1; UNLOCK.logoClicks = 0; }
      }
    });
  }
  const themeBtn = document.getElementById("theme-btn");
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      armResetTimer();
      if (UNLOCK.stage === 1) {
        UNLOCK.themeClicks++;
        if (UNLOCK.themeClicks >= 4) {
          UNLOCK.stage = 3; UNLOCK.themeClicks = 0;
          setTimeout(showUnlockModal, 200);
        }
      }
    });
  }
}

/* ============================================================
   STATE STORE
   ============================================================ */
const store = {
  state: {
    vms: {},
    recentBricks: [],
    symbol: "",
    selectedVm: null,
    selectedTrade: null,
    route: "overview",
    theme: localStorage.getItem("jg-theme") || "dark",
    navExpanded: localStorage.getItem("jg-nav-expanded") === "true",
    connected: false,
    tradeFilter: "all",
    tradeTimeframe: "all",
    equityTimeframe: "all",
    logFilter: {vm: "all", severity: "all", type: "all"},
  },
  listeners: new Set(),
  set(patch) {
    Object.assign(this.state, patch);
    this.listeners.forEach(fn => fn(this.state));
  },
  subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
};

/* ============================================================
   UTILITIES
   ============================================================ */
function fmt$(v, decimals = 2) {
  if (v == null || isNaN(v)) return "—";
  return "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function pnlClass(v) { return v > 0 ? "pos" : v < 0 ? "neg" : ""; }
function pnlSign(v) { return v >= 0 ? "+" : ""; }
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function fmtTime(sec) {
  if (!sec) return "—";
  return new Date(sec * 1000).toISOString().replace("T", " ").slice(0, 19) + "Z";
}
function getCSSVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function getAllTrades() {
  const trades = [];
  for (const v of Object.values(store.state.vms)) {
    for (const t of (v.trades || [])) trades.push({ ...t, vm_id: v.vm_id });
  }
  trades.sort((a, b) => (b.entry_ts || 0) - (a.entry_ts || 0));
  return trades;
}

function fleetOverallStats() {
  const vms = Object.values(store.state.vms);
  let bal = 0, positions = 0, connected = 0;
  const allTrades = getAllTrades();
  let totalPnl = 0, wins = 0, closedTrades = 0;
  for (const v of vms) {
    bal += v.balance || 0;
    positions += v.position_count || 0;
    if (v.status === "online") connected++;
  }
  for (const t of allTrades) {
    if (t.exit_ts && t.realized_pnl != null) {
      totalPnl += t.realized_pnl;
      closedTrades++;
      if (t.realized_pnl > 0) wins++;
    }
  }
  return {
    totalBalance: bal,
    totalPnl,
    closedTrades,
    wr: closedTrades > 0 ? (wins / closedTrades * 100) : 0,
    positions,
    connected,
    vmCount: vms.length,
  };
}

/* ============================================================
   ROUTER
   ============================================================ */
function navigate(route) { window.location.hash = "#/" + route; }
function parseRoute() {
  const hash = window.location.hash.slice(2) || "overview";
  const [route, ...rest] = hash.split("/");
  return { route: route || "overview", params: rest };
}
window.addEventListener("hashchange", () => {
  const { route, params } = parseRoute();
  if (params[0]) store.set({ selectedVm: params[0] });
  store.set({ route });
});

/* ============================================================
   THEME
   ============================================================ */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("jg-theme", theme);
  const themeColorMap = {
    dark: "#08090c", midnight: "#0a0612", ocean: "#051822", forest: "#0a1410",
    glass: "#0a0f1e", light: "#ffffff", paper: "#faf7f2", mint: "#f0fdf6", sunset: "#1a0a1f"
  };
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", themeColorMap[theme] || "#08090c");
}

function cycleTheme() {
  const themes = ["dark", "midnight", "ocean", "forest", "glass", "light", "paper", "mint", "sunset"];
  const next = themes[(themes.indexOf(store.state.theme) + 1) % themes.length];
  applyTheme(next);
  store.set({ theme: next });
  toast(`Theme: ${next}`, "info");
}

/* ============================================================
   TOASTS
   ============================================================ */
function toast(msg, type = "info", duration = 3200) {
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.innerHTML = escapeHtml(msg);
  document.getElementById("toast-container").appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 300);
  }, duration);
}

/* ============================================================
   WEBSOCKET
   ============================================================ */
let ws = null;
function connectWS() {
  const url = `ws://${window.location.host}/ws`;
  ws = new WebSocket(url);
  ws.onopen = () => {
    store.set({ connected: true });
    ws.send(JSON.stringify({ type: "hello" }));
  };
  ws.onclose = () => {
    store.set({ connected: false });
    setTimeout(connectWS, 3000);
  };
  ws.onerror = (e) => console.error("WS error", e);
  ws.onmessage = (ev) => {
    try { handleMessage(JSON.parse(ev.data)); }
    catch (e) { console.error(e); }
  };
}

function sendCommand(action, vm_id, extra = {}) {
  if (!ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ type: "command", action, vm_id, ...extra }));
}

function handleMessage(msg) {
  const t = msg.type;
  if (t === "initial_state") {
    const incoming = { ...msg.vms };
    const existing = { ...store.state.vms };
    const merged = {};
    for (const vid in incoming) {
      const inc = incoming[vid];
      const old = existing[vid] || {};
      merged[vid] = {
        ...old, ...inc,
        balance: inc.balance || old.balance || 0,
        equity: inc.equity || old.equity || 0,
        trades: inc.trades && inc.trades.length ? inc.trades : (old.trades || []),
        events: inc.events && inc.events.length ? inc.events : (old.events || []),
        equity_history: inc.equity_history && inc.equity_history.length ? inc.equity_history : (old.equity_history || []),
      };
    }
    for (const vid in existing) {
      if (!(vid in merged)) merged[vid] = existing[vid];
    }
    const selected = store.state.selectedVm || Object.keys(merged)[0] || null;
    store.set({
      vms: merged,
      selectedVm: selected,
      recentBricks: msg.recent_bricks || [],
      symbol: msg.symbol || "",
    });
    return;
  }
  if (t === "bar_new") {
    const bricks = [...(store.state.recentBricks || []), msg.brick];
    if (bricks.length > 200) bricks.shift();
    store.set({ recentBricks: bricks });
    // Live chart handles update via subscription
    if (store.state.route === "live" && charts.live) {
      try {
        charts.live.series.update(msg.brick);
        updateLiveMAs();
      } catch {}
    }
    return;
  }
  if (t === "vm_event") {
    const vms = { ...store.state.vms };
    const vid = msg.vm_id;
    if (!vms[vid]) return;
    const vm = { ...vms[vid] };
    const et = msg.event_type;
    const d = msg.data;

    if (et === "SIGNAL_ACK" && d.status === "filled") {
      const trade = {
        trade_id: d.position_id,
        vm_id: vid,
        signal_id: d.signal_id,
        symbol: d.symbol,
        direction: d.direction,
        entry_ts: d.fill_time,
        entry_price: d.fill_price,
        sl_price: d.sl_price,
        lots: d.lots,
        mt5_ticket: d.mt5_ticket,
        exit_ts: null,
        exit_price: null,
        realized_pnl: null,
      };
      vm.trades = [...vm.trades, trade];
      toast(`📈 ${vid}: ${d.direction === 1 ? "LONG" : "SHORT"} filled @ ${d.fill_price.toFixed(2)}`, "success");
    } else if (et === "POSITION_CLOSED") {
      vm.trades = vm.trades.map(tr =>
        tr.trade_id === d.position_id ? {
          ...tr, exit_ts: d.exit_time, exit_price: d.exit_price,
          realized_pnl: d.realized_pnl, exit_reason: d.exit_reason,
        } : tr
      );
      const pnl = d.realized_pnl || 0;
      toast(`${pnl > 0 ? "✅" : "🚨"} ${vid}: ${pnl > 0 ? "WIN" : "LOSS"} ${fmt$(pnl)}`, pnl > 0 ? "success" : "error");
    }
    vms[vid] = vm;
    store.set({ vms });
    return;
  }
  if (t === "vm_status_change") {
    const vms = { ...store.state.vms };
    if (vms[msg.vm_id]) {
      vms[msg.vm_id] = { ...vms[msg.vm_id], status: msg.status };
      store.set({ vms });
    }
    return;
  }
  if (t === "signal_open") {
    // Info toast
    return;
  }
  if (t === "toast") {
    toast(msg.message, msg.level || "info");
    return;
  }
  if (t === "config_result") {
    if (msg.ok) toast(`✅ Config pushed to ${msg.vm_id}`, "success");
    else toast(`❌ Config rejected: ${(msg.errors || []).join("; ")}`, "error", 6000);
    return;
  }
}

/* ============================================================
   HMA COMPUTATION (client-side for chart)
   ============================================================ */
function computeWMA(closes, period) {
  const out = new Array(closes.length).fill(null);
  if (closes.length < period) return out;
  const wSum = period * (period + 1) / 2;
  for (let i = period - 1; i < closes.length; i++) {
    let s = 0;
    for (let k = 0; k < period; k++) s += closes[i - period + 1 + k] * (k + 1);
    out[i] = s / wSum;
  }
  return out;
}
function computeHMA(closes, period) {
  const half = Math.max(1, Math.floor(period / 2));
  const sqrtP = Math.max(1, Math.round(Math.sqrt(period)));
  const n = closes.length;
  const wmaHalf = computeWMA(closes, half);
  const wmaFull = computeWMA(closes, period);
  const diff = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (wmaHalf[i] !== null && wmaFull[i] !== null) diff[i] = 2 * wmaHalf[i] - wmaFull[i];
  }
  const validStart = period - 1;
  if (n - validStart < sqrtP) return new Array(n).fill(null);
  const diffValid = diff.slice(validStart).map(v => v ?? 0);
  const smoothed = computeWMA(diffValid, sqrtP);
  const out = new Array(n).fill(null);
  for (let i = 0; i < smoothed.length; i++) {
    if (smoothed[i] !== null) out[validStart + i] = smoothed[i];
  }
  return out;
}

/* ============================================================
   CHART REGISTRY
   ============================================================ */
const charts = { live: null, equity: null };

/* ============================================================
   OVERVIEW — overall stats + ApexCharts equity + trades + activity
   ============================================================ */
function renderOverview() {
  const totals = fleetOverallStats();
  const vms = Object.values(store.state.vms);
  const allTrades = getAllTrades();
  const allEvents = [];
  for (const v of vms) for (const e of (v.events || [])) allEvents.push({ ...e, vm_id: v.vm_id });
  allEvents.sort((a, b) => (b.ts || 0) - (a.ts || 0));

  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Dashboard</div>
          <div class="page-subtitle">Overall fleet performance</div>
        </div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">Total Balance</div>
          <div class="kpi-value">${fmt$(totals.totalBalance, 0)}</div>
          <div class="kpi-sub"><span>${totals.vmCount} VM${totals.vmCount !== 1 ? "s" : ""}</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Total PnL</div>
          <div class="kpi-value ${pnlClass(totals.totalPnl)}">${pnlSign(totals.totalPnl)}${fmt$(totals.totalPnl)}</div>
          <div class="kpi-sub"><span>${totals.closedTrades} trades</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Overall WR</div>
          <div class="kpi-value">${totals.closedTrades > 0 ? totals.wr.toFixed(1) + "%" : "—"}</div>
          <div class="kpi-sub"><span>${totals.closedTrades > 0 ? (totals.wr >= 50 ? "profitable" : "review") : "no trades yet"}</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Active Positions</div>
          <div class="kpi-value">${totals.positions}</div>
          <div class="kpi-sub"><span>${totals.connected} online</span></div>
        </div>
      </div>

      <div class="card" style="margin-bottom: var(--space-4);">
        <div class="card-header">
          <div>
            <div class="card-title">Equity Curve</div>
            <div class="card-subtitle">Cumulative PnL across all trades from all VMs</div>
          </div>
          <div class="chip-row" style="margin: 0;">
            ${["all", "today", "week", "month"].map(x =>
              `<div class="chip ${store.state.equityTimeframe === x ? 'active' : ''}" data-eq-tf="${x}">${x === "all" ? "All time" : x === "today" ? "Today" : x === "week" ? "7 days" : "30 days"}</div>`
            ).join("")}
          </div>
        </div>
        <div class="card-body">
          <div id="equity-chart-container" style="height: 340px; width: 100%;"></div>
        </div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-header">
            <div class="card-title">VMs</div>
            <div class="card-subtitle">${vms.length} total</div>
          </div>
          <div class="list-compact list-scrollable">
            ${vms.length === 0 ? emptyState("No VMs connected", "Waiting…") :
              vms.map(v => {
                const status = v.status || "unknown";
                const vmTrades = (v.trades || []).filter(t => t.exit_ts);
                const vmPnl = vmTrades.reduce((s, t) => s + (t.realized_pnl || 0), 0);
                return `
                  <div class="list-row node-row" data-vm="${escapeHtml(v.vm_id)}">
                    <span class="node-status-dot ${status}"></span>
                    <span class="node-name">${escapeHtml(v.vm_id)}</span>
                    <span class="node-balance">${fmt$(v.balance || 0, 0)}</span>
                    <span class="node-pnl ${pnlClass(vmPnl)}">${pnlSign(vmPnl)}${fmt$(vmPnl, 0)}</span>
                  </div>
                `;
              }).join("")
            }
          </div>
        </div>
        <div class="card">
          <div class="card-header">
            <div class="card-title">Recent Trades</div>
            <div class="card-subtitle">Last 50 across fleet</div>
          </div>
          <div class="list-compact list-scrollable">
            ${allTrades.length === 0 ? emptyState("No trades yet", "Waiting for signals…") :
              allTrades.slice(0, 50).map(t => tradeRowHTML(t, true)).join("")
            }
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">Activity</div>
          <div class="card-subtitle">Last 100 events</div>
        </div>
        <div class="list-compact list-scrollable" style="max-height: 400px;">
          ${allEvents.length === 0 ? emptyState("No activity yet", "") :
            allEvents.slice(0, 100).map(e => activityHTML(e)).join("")
          }
        </div>
      </div>
    </div>
  `;

  // Render equity chart with ApexCharts
  setTimeout(() => renderEquityChart(), 50);

  document.querySelectorAll("[data-eq-tf]").forEach(el => {
    el.addEventListener("click", () => store.set({ equityTimeframe: el.dataset.eqTf }));
  });
  document.querySelectorAll("[data-vm]").forEach(el => {
    el.addEventListener("click", () => {
      store.set({ selectedVm: el.dataset.vm });
      navigate("live/" + el.dataset.vm);
    });
  });
  document.querySelectorAll(".trade-row[data-tid]").forEach(row => {
    row.addEventListener("click", () => focusTrade(row.dataset.vm, row.dataset.tid));
  });
}

function renderEquityChart() {
  const container = document.getElementById("equity-chart-container");
  if (!container) return;

  // Destroy old chart
  if (charts.equity) {
    try { charts.equity.destroy(); } catch {}
    charts.equity = null;
  }

  // Build cumulative equity curve from all trades sorted by exit_ts
  const allTrades = getAllTrades()
    .filter(t => t.exit_ts && t.realized_pnl != null)
    .sort((a, b) => (a.exit_ts || 0) - (b.exit_ts || 0));

  // Apply timeframe filter
  const now = Date.now() / 1000;
  const dayStart = Math.floor(now / 86400) * 86400;
  const weekStart = dayStart - 7 * 86400;
  const monthStart = dayStart - 30 * 86400;
  let filtered = allTrades;
  const tf = store.state.equityTimeframe;
  if (tf === "today") filtered = filtered.filter(t => t.exit_ts >= dayStart);
  else if (tf === "week") filtered = filtered.filter(t => t.exit_ts >= weekStart);
  else if (tf === "month") filtered = filtered.filter(t => t.exit_ts >= monthStart);

  if (filtered.length === 0) {
    container.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:center; height:100%; color:var(--text-muted); font-family:var(--font-mono); font-size:12px;">
        No closed trades in this timeframe
      </div>
    `;
    return;
  }

  let cum = 0;
  const points = filtered.map(t => {
    cum += t.realized_pnl || 0;
    return { x: t.exit_ts * 1000, y: parseFloat(cum.toFixed(2)) };
  });

  const isPositive = cum >= 0;
  const accent = getCSSVar("--accent");
  const green = getCSSVar("--green");
  const red = getCSSVar("--red");
  const textDim = getCSSVar("--text-dim");
  const border = getCSSVar("--border");
  const bg1 = getCSSVar("--bg-1");

  const options = {
    chart: {
      type: 'area',
      height: 340,
      background: 'transparent',
      foreColor: textDim,
      toolbar: {
        show: true,
        tools: { download: false, selection: false, zoom: true, zoomin: true, zoomout: true, pan: true, reset: true }
      },
      animations: { enabled: true, easing: 'easeout', speed: 400 },
      zoom: { enabled: true, type: 'x' },
    },
    series: [{ name: 'Cumulative PnL', data: points }],
    stroke: { curve: 'smooth', width: 2, colors: [isPositive ? green : red] },
    fill: {
      type: 'gradient',
      gradient: {
        shade: 'dark',
        type: 'vertical',
        shadeIntensity: 0.5,
        gradientToColors: [isPositive ? green : red],
        inverseColors: false,
        opacityFrom: 0.4,
        opacityTo: 0.05,
        stops: [0, 100],
      }
    },
    dataLabels: { enabled: false },
    grid: { borderColor: border, strokeDashArray: 3, xaxis: { lines: { show: true } }, yaxis: { lines: { show: true } } },
    xaxis: {
      type: 'datetime',
      labels: { style: { colors: textDim, fontSize: '11px' } },
      axisBorder: { color: border },
      axisTicks: { color: border },
    },
    yaxis: {
      labels: {
        style: { colors: textDim, fontSize: '11px' },
        formatter: (v) => "$" + v.toLocaleString(undefined, { maximumFractionDigits: 0 })
      },
    },
    tooltip: {
      theme: 'dark',
      x: { format: 'yyyy-MM-dd HH:mm' },
      y: { formatter: (v) => "$" + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
    },
    markers: { size: 0, hover: { size: 6 } },
    annotations: {
      yaxis: [{ y: 0, borderColor: textDim, strokeDashArray: 4, opacity: 0.5 }]
    }
  };

  charts.equity = new ApexCharts(container, options);
  charts.equity.render();
}

/* ============================================================
   HELPERS FOR ROW / ACTIVITY / EMPTY
   ============================================================ */
function tradeRowHTML(t, showVm = false) {
  const isWin = (t.realized_pnl || 0) > 0;
  const dir = t.direction === 1 ? "LONG" : "SHORT";
  const pnl = t.realized_pnl || 0;
  const closed = t.exit_ts != null;
  const dateStr = t.entry_ts ? new Date(t.entry_ts * 1000).toISOString().replace("T", " ").slice(0, 16) : "—";
  const priceStr = t.entry_price ? `${(t.entry_price).toFixed(2)} → ${(t.exit_price || 0).toFixed(2)}` : "—";
  return `
    <div class="trade-row" data-tid="${escapeHtml(t.trade_id)}" data-vm="${escapeHtml(t.vm_id || '')}">
      <div class="trade-id">#${String(t.trade_id).slice(0, 8)}</div>
      ${closed ? `<div class="badge ${isWin ? 'WIN' : 'LOSS'}">${isWin ? 'W' : 'L'}</div>` : `<div class="badge" style="background:var(--accent-dim);color:var(--accent);">OPEN</div>`}
      <div class="dir-arrow ${dir}">${dir === 'LONG' ? '▲' : '▼'}</div>
      <div class="trade-time">${dateStr}${showVm && t.vm_id ? ' · ' + escapeHtml(t.vm_id) : ''}</div>
      <div></div>
      <div class="trade-price">${priceStr}</div>
      <div class="trade-pnl ${pnlClass(pnl)}">${closed ? pnlSign(pnl) + fmt$(pnl) : '—'}</div>
    </div>
  `;
}

function activityHTML(e) {
  const map = {
    "SIGNAL_ACK": { c: "trade", i: "▲" },
    "POSITION_CLOSED": { c: "trade", i: "◆" },
    "VM_ONLINE": { c: "info", i: "🚀" },
    "VM_ERROR": { c: "warn", i: "✕" },
    "CONFIG_UPDATED": { c: "info", i: "✎" },
    "CONFIG_APPLIED": { c: "info", i: "✓" },
  };
  const meta = map[e.type] || { c: "info", i: "•" };
  const ts = e.ts ? new Date(e.ts * 1000).toISOString().replace("T", " ").slice(0, 16) : "—";
  return `
    <div class="activity-item">
      <div class="activity-icon ${meta.c}">${meta.i}</div>
      <div class="activity-content">
        <div class="activity-message">${escapeHtml(e.message || e.type)}</div>
        <div class="activity-meta">${ts}${e.vm_id ? ' · ' + escapeHtml(e.vm_id) : ''}</div>
      </div>
    </div>
  `;
}

function emptyState(title, msg) {
  return `
    <div class="empty-state">
      <div class="empty-icon">◌</div>
      <div class="empty-title">${escapeHtml(title)}</div>
      ${msg ? `<div class="empty-msg">${escapeHtml(msg)}</div>` : ''}
    </div>
  `;
}

/* ============================================================
   LIVE VIEW — uses mother's rolling brick buffer for instant chart
   ============================================================ */
function renderLive() {
  document.getElementById("main").innerHTML = `
    <div class="live-container">
      <div class="live-toolbar">
        <div class="card-title">Live · ${escapeHtml(store.state.symbol || 'no symbol')}</div>
        <div style="width:24px"></div>
        <label class="ma-toggle">
          <input type="checkbox" id="ma-main" checked>
          <span class="ma-swatch main"></span>
          <span class="ma-toggle-label">HMA-21</span>
        </label>
        <label class="ma-toggle">
          <input type="checkbox" id="ma-fast" checked>
          <span class="ma-swatch fast"></span>
          <span class="ma-toggle-label">HMA-14</span>
        </label>
        <div style="margin-left:auto;">
          <span class="session-badge" id="session-badge">Session status…</span>
        </div>
      </div>
      <div class="live-chart-wrap" id="live-chart-wrap"></div>
    </div>
  `;
  setTimeout(() => { initLiveChart(); updateSessionBadge(); }, 30);
  document.getElementById("ma-main")?.addEventListener("change", updateLiveMAs);
  document.getElementById("ma-fast")?.addEventListener("change", updateLiveMAs);
}

function initLiveChart() {
  const el = document.getElementById("live-chart-wrap");
  if (!el) return;

  const bricks = store.state.recentBricks || [];
  if (bricks.length === 0) {
    el.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:center; height:100%; flex-direction:column; gap:12px; padding: var(--space-6);">
        <div style="font-size:40px; opacity:0.4;">📊</div>
        <div style="color:var(--text-dim); font-family:var(--font-mono); font-size:13px; font-weight:600;">
          Waiting for bars from mother's tick stream…
        </div>
      </div>
    `;
    return;
  }

  el.innerHTML = "";
  const chart = LightweightCharts.createChart(el, {
    layout: {
      background: { type: "solid", color: getCSSVar("--bg-0") },
      textColor: getCSSVar("--text-dim"),
      fontFamily: getComputedStyle(document.body).fontFamily,
      fontSize: 11
    },
    grid: {
      vertLines: { color: getCSSVar("--bg-2") },
      horzLines: { color: getCSSVar("--bg-2") }
    },
    timeScale: {
      borderColor: getCSSVar("--border"),
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 8
    },
    rightPriceScale: { borderColor: getCSSVar("--border") },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    width: el.clientWidth,
    height: el.clientHeight,
  });

  const series = chart.addCandlestickSeries({
    upColor: getCSSVar("--green"),
    downColor: getCSSVar("--red"),
    borderUpColor: getCSSVar("--green"),
    borderDownColor: getCSSVar("--red"),
    wickUpColor: getCSSVar("--green"),
    wickDownColor: getCSSVar("--red"),
  });

  const mainMA = chart.addLineSeries({
    color: getCSSVar("--purple"), lineWidth: 2,
    priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
  });
  const fastMA = chart.addLineSeries({
    color: getCSSVar("--cyan"), lineWidth: 2,
    priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
  });

  charts.live = { chart, series, mainMA, fastMA };

  const seenTimes = new Set();
  const cleanBars = [];
  for (const b of bricks) {
    if (!seenTimes.has(b.time)) {
      seenTimes.add(b.time);
      cleanBars.push(b);
    }
  }
  cleanBars.sort((a, b) => a.time - b.time);
  series.setData(cleanBars);
  updateLiveMAs();

  try { chart.timeScale().fitContent(); } catch {}

  if (charts.live._resizeHandler) {
    window.removeEventListener("resize", charts.live._resizeHandler);
  }
  charts.live._resizeHandler = () => {
    if (charts.live && charts.live.chart) {
      chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
    }
  };
  window.addEventListener("resize", charts.live._resizeHandler);
}

function updateLiveMAs() {
  if (!charts.live) return;
  const bricks = store.state.recentBricks || [];
  if (bricks.length < 30) return;
  const showMain = document.getElementById("ma-main")?.checked;
  const showFast = document.getElementById("ma-fast")?.checked;
  const closes = bricks.map(b => b.close);
  const mainVals = computeHMA(closes, 21);
  const fastVals = computeHMA(closes, 14);
  const mainData = [], fastData = [];
  for (let i = 0; i < bricks.length; i++) {
    if (mainVals[i] !== null) mainData.push({ time: bricks[i].time, value: mainVals[i] });
    if (fastVals[i] !== null) fastData.push({ time: bricks[i].time, value: fastVals[i] });
  }
  charts.live.mainMA.setData(showMain ? mainData : []);
  charts.live.fastMA.setData(showFast ? fastData : []);
}

function updateSessionBadge() {
  const el = document.getElementById("session-badge");
  if (!el) return;
  const now = new Date();
  const utcHour = now.getUTCHours();
  const utcWeekday = now.getUTCDay();
  const cstHour = (utcHour - 6 + 24) % 24;
  const NY = new Set([8, 9, 10, 11, 12, 13, 14, 15, 16]);
  const isWeekend = utcWeekday === 0 || utcWeekday === 6;
  if (isWeekend) {
    el.className = "session-badge";
    el.textContent = `Weekend · NY closed`;
    return;
  }
  if (NY.has(cstHour)) {
    el.className = "session-badge active";
    el.textContent = `NY active · CT ${cstHour}:00`;
  } else {
    let h = 8 - cstHour;
    if (h <= 0) h += 24;
    el.className = "session-badge";
    el.textContent = `NY closed · opens in ${h}h (CT)`;
  }
}

/* ============================================================
   TRADES
   ============================================================ */
function renderTrades() {
  const filter = store.state.tradeFilter;
  const tf = store.state.tradeTimeframe;
  let trades = getAllTrades();
  const now = Date.now() / 1000;
  const dayStart = Math.floor(now / 86400) * 86400;
  const weekStart = dayStart - 7 * 86400;
  const monthStart = dayStart - 30 * 86400;
  if (tf === "today") trades = trades.filter(t => t.entry_ts >= dayStart);
  else if (tf === "week") trades = trades.filter(t => t.entry_ts >= weekStart);
  else if (tf === "month") trades = trades.filter(t => t.entry_ts >= monthStart);

  if (filter === "LONG") trades = trades.filter(t => t.direction === 1);
  else if (filter === "SHORT") trades = trades.filter(t => t.direction === -1);
  else if (filter === "WIN") trades = trades.filter(t => (t.realized_pnl || 0) > 0);
  else if (filter === "LOSS") trades = trades.filter(t => (t.realized_pnl || 0) <= 0 && t.exit_ts);
  else if (filter === "OPEN") trades = trades.filter(t => !t.exit_ts);

  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Trades</div>
          <div class="page-subtitle">${trades.length} shown</div>
        </div>
      </div>
      <div class="chip-row">
        ${["all", "today", "week", "month"].map(x =>
          `<div class="chip ${tf === x ? 'active' : ''}" data-tf="${x}">${x === "all" ? "All time" : x === "today" ? "Today" : x === "week" ? "7 days" : "30 days"}</div>`
        ).join("")}
        <div style="width:20px"></div>
        ${["all", "LONG", "SHORT", "WIN", "LOSS", "OPEN"].map(f =>
          `<div class="chip ${filter === f ? 'active' : ''}" data-filter="${f}">${f}</div>`
        ).join("")}
      </div>
      <div class="card">
        <div class="list-compact">
          ${trades.length === 0 ? emptyState("No trades match", "Try different filters") :
            trades.slice(0, 500).map(t => tradeRowHTML(t, true)).join("")
          }
        </div>
      </div>
    </div>
  `;
  document.querySelectorAll("[data-tf]").forEach(el => el.addEventListener("click", () => store.set({ tradeTimeframe: el.dataset.tf })));
  document.querySelectorAll("[data-filter]").forEach(el => el.addEventListener("click", () => store.set({ tradeFilter: el.dataset.filter })));
  document.querySelectorAll(".trade-row[data-tid]").forEach(row => {
    row.addEventListener("click", () => focusTrade(row.dataset.vm, row.dataset.tid));
  });
}

/* ============================================================
   STATS (per VM)
   ============================================================ */
function vmSelectorHTML(currentVm) {
  const vms = Object.values(store.state.vms);
  if (vms.length === 0) return "";
  return `
    <select class="config-select" id="vm-selector" style="min-width:180px;">
      <option value="">— Select VM —</option>
      ${vms.map(v => `
        <option value="${escapeHtml(v.vm_id)}" ${v.vm_id === currentVm ? 'selected' : ''}>
          ${escapeHtml(v.vm_id)} · ${escapeHtml(v.status || 'unknown')}
        </option>
      `).join("")}
    </select>
  `;
}
function bindVmSelector(routeName) {
  document.getElementById("vm-selector")?.addEventListener("change", (e) => {
    const vid = e.target.value;
    if (!vid) return;
    store.set({ selectedVm: vid });
    if (routeName === "config") { configOriginal = null; configDraft = null; }
    navigate(routeName + "/" + vid);
  });
}

function renderStats() {
  const vms = Object.values(store.state.vms);
  if (vms.length === 0) {
    document.getElementById("main").innerHTML = `<div class="page">${emptyState("No VMs", "Waiting")}</div>`;
    return;
  }
  if (!store.state.selectedVm) store.state.selectedVm = vms[0].vm_id;
  const vm = store.state.vms[store.state.selectedVm];
  if (!vm) return;

  const trades = (vm.trades || []).filter(t => t.exit_ts);
  const wins = trades.filter(t => (t.realized_pnl || 0) > 0);
  const losses = trades.filter(t => (t.realized_pnl || 0) <= 0);
  const wr = trades.length > 0 ? (wins.length / trades.length * 100) : 0;
  const net = trades.reduce((s, t) => s + (t.realized_pnl || 0), 0);
  const wSum = wins.reduce((s, t) => s + t.realized_pnl, 0);
  const lSum = losses.reduce((s, t) => s + (t.realized_pnl || 0), 0);
  const pf = lSum < 0 ? (wSum / Math.abs(lSum)) : (wSum > 0 ? Infinity : 0);
  const avgWin = wins.length > 0 ? wSum / wins.length : 0;
  const avgLoss = losses.length > 0 ? lSum / losses.length : 0;
  const expectancy = trades.length > 0 ? net / trades.length : 0;
  const longs = trades.filter(t => t.direction === 1);
  const shorts = trades.filter(t => t.direction === -1);
  const longNet = longs.reduce((s, t) => s + (t.realized_pnl || 0), 0);
  const shortNet = shorts.reduce((s, t) => s + (t.realized_pnl || 0), 0);
  const bal = vm.balance || 0;

  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Statistics</div>
          <div class="page-subtitle">${escapeHtml(vm.vm_id)}</div>
        </div>
        <div>${vmSelectorHTML(store.state.selectedVm)}</div>
      </div>
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">Win Rate</div><div class="kpi-value">${trades.length > 0 ? wr.toFixed(1) + "%" : "—"}</div><div class="kpi-sub"><span>${wins.length}W / ${losses.length}L</span></div></div>
        <div class="kpi-card"><div class="kpi-label">Profit Factor</div><div class="kpi-value">${isFinite(pf) && pf > 0 ? pf.toFixed(2) : "—"}</div><div class="kpi-sub"><span>${pf >= 1.2 ? "deployable" : "review"}</span></div></div>
        <div class="kpi-card"><div class="kpi-label">Net PnL</div><div class="kpi-value ${pnlClass(net)}">${pnlSign(net)}${fmt$(net, 0)}</div><div class="kpi-sub"><span>${trades.length} trades</span></div></div>
        <div class="kpi-card"><div class="kpi-label">Balance</div><div class="kpi-value">${fmt$(bal, 0)}</div><div class="kpi-sub"><span>${escapeHtml(vm.status || "?")}</span></div></div>
      </div>
      <div class="grid-3">
        <div class="card"><div class="card-header"><div class="card-title">Averages</div></div><div class="card-body">
          <div class="detail-row"><span class="k">Avg win</span><span class="v pos">${fmt$(avgWin)}</span></div>
          <div class="detail-row"><span class="k">Avg loss</span><span class="v neg">${fmt$(avgLoss)}</span></div>
          <div class="detail-row"><span class="k">Expectancy</span><span class="v ${pnlClass(expectancy)}">${fmt$(expectancy)}</span></div>
          <div class="detail-row"><span class="k">Best</span><span class="v pos">${trades.length ? fmt$(Math.max(...trades.map(t => t.realized_pnl || 0))) : "—"}</span></div>
          <div class="detail-row"><span class="k">Worst</span><span class="v neg">${trades.length ? fmt$(Math.min(...trades.map(t => t.realized_pnl || 0))) : "—"}</span></div>
        </div></div>
        <div class="card"><div class="card-header"><div class="card-title">Longs</div></div><div class="card-body">
          <div class="detail-row"><span class="k">Count</span><span class="v">${longs.length}</span></div>
          <div class="detail-row"><span class="k">Net</span><span class="v ${pnlClass(longNet)}">${pnlSign(longNet)}${fmt$(longNet)}</span></div>
          <div class="detail-row"><span class="k">WR</span><span class="v">${longs.length > 0 ? (longs.filter(t => (t.realized_pnl || 0) > 0).length / longs.length * 100).toFixed(1) + "%" : "—"}</span></div>
        </div></div>
        <div class="card"><div class="card-header"><div class="card-title">Shorts</div></div><div class="card-body">
          <div class="detail-row"><span class="k">Count</span><span class="v">${shorts.length}</span></div>
          <div class="detail-row"><span class="k">Net</span><span class="v ${pnlClass(shortNet)}">${pnlSign(shortNet)}${fmt$(shortNet)}</span></div>
          <div class="detail-row"><span class="k">WR</span><span class="v">${shorts.length > 0 ? (shorts.filter(t => (t.realized_pnl || 0) > 0).length / shorts.length * 100).toFixed(1) + "%" : "—"}</span></div>
        </div></div>
      </div>
    </div>
  `;
  bindVmSelector("stats");
}

/* ============================================================
   FLEET (cards per VM)
   ============================================================ */
function renderFleet() {
  const vms = Object.values(store.state.vms);
  const totals = fleetOverallStats();
  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Fleet</div>
          <div class="page-subtitle">${vms.length} VM${vms.length !== 1 ? "s" : ""} · ${fmt$(totals.totalBalance, 0)}</div>
        </div>
      </div>
      <div class="node-grid">
        ${vms.length === 0 ? emptyState("No VMs", "Waiting…") :
          vms.map(v => {
            const trades = (v.trades || []).filter(t => t.exit_ts);
            const net = trades.reduce((s, t) => s + (t.realized_pnl || 0), 0);
            const wins = trades.filter(t => (t.realized_pnl || 0) > 0).length;
            const wr = trades.length > 0 ? (wins / trades.length * 100) : 0;
            const status = v.status || "unknown";
            return `
              <div class="node-card" data-vm="${escapeHtml(v.vm_id)}">
                <div class="node-card-header">
                  <div class="node-card-name">
                    <span class="node-status-dot ${status}"></span>
                    ${escapeHtml(v.vm_id)}
                  </div>
                  <span class="status-pill ${status}">${status}</span>
                </div>
                <div class="node-card-balance">${fmt$(v.balance || 0, 0)}</div>
                <div class="node-card-metrics">
                  <div class="node-card-metric"><div class="lbl">Trades</div><div class="val">${trades.length}</div></div>
                  <div class="node-card-metric"><div class="lbl">Win%</div><div class="val">${trades.length > 0 ? wr.toFixed(0) + "%" : "—"}</div></div>
                  <div class="node-card-metric"><div class="lbl">Net</div><div class="val ${pnlClass(net)}">${pnlSign(net)}${fmt$(net, 0)}</div></div>
                </div>
                <div class="node-card-actions">
                  <button class="node-btn" data-action="halt" data-vm-id="${escapeHtml(v.vm_id)}">Halt</button>
                  <button class="node-btn" data-action="resume" data-vm-id="${escapeHtml(v.vm_id)}">Resume</button>
                  <button class="node-btn danger" data-action="close_all" data-vm-id="${escapeHtml(v.vm_id)}">Close</button>
                </div>
              </div>
            `;
          }).join("")
        }
      </div>
    </div>
  `;
  document.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const action = btn.dataset.action;
      const vmId = btn.dataset.vmId;
      if (confirm(`${action} ${vmId}?`)) {
        sendCommand(action, vmId);
        toast(`Sent ${action} to ${vmId}`, "info");
      }
    });
  });
  document.querySelectorAll(".node-card[data-vm]").forEach(card => {
    card.addEventListener("click", () => {
      store.set({ selectedVm: card.dataset.vm });
      navigate("live/" + card.dataset.vm);
    });
  });
}

/* ============================================================
   LOGS
   ============================================================ */
function renderLogs() {
  const vms = Object.values(store.state.vms);
  const filter = store.state.logFilter;
  const allEvents = [];
  for (const v of vms) for (const e of (v.events || [])) allEvents.push({ ...e, vm_id: v.vm_id });
  allEvents.sort((a, b) => (b.ts || 0) - (a.ts || 0));
  let filtered = allEvents;
  if (filter.vm !== "all") filtered = filtered.filter(e => e.vm_id === filter.vm);
  if (filter.severity !== "all") filtered = filtered.filter(e => (e.severity || "INFO") === filter.severity);
  const eventTypes = [...new Set(allEvents.map(e => e.type))].sort();
  if (filter.type && filter.type !== "all") filtered = filtered.filter(e => e.type === filter.type);

  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Logs</div>
          <div class="page-subtitle">${filtered.length} of ${allEvents.length} events</div>
        </div>
      </div>
      <div class="chip-row">
        <span style="font-size:11px; color:var(--text-muted); align-self:center;">VM:</span>
        <div class="chip ${filter.vm === 'all' ? 'active' : ''}" data-vm-filter="all">All</div>
        ${vms.map(v => `<div class="chip ${filter.vm === v.vm_id ? 'active' : ''}" data-vm-filter="${escapeHtml(v.vm_id)}">${escapeHtml(v.vm_id)}</div>`).join("")}
      </div>
      <div class="chip-row">
        <span style="font-size:11px; color:var(--text-muted); align-self:center;">Severity:</span>
        ${["all", "INFO", "WARNING", "ERROR"].map(s => `<div class="chip ${filter.severity === s ? 'active' : ''}" data-sev-filter="${s}">${s}</div>`).join("")}
      </div>
      ${eventTypes.length > 0 ? `
      <div class="chip-row">
        <span style="font-size:11px; color:var(--text-muted); align-self:center;">Type:</span>
        <div class="chip ${!filter.type || filter.type === 'all' ? 'active' : ''}" data-type-filter="all">All types</div>
        ${eventTypes.slice(0, 15).map(t => `<div class="chip ${filter.type === t ? 'active' : ''}" data-type-filter="${escapeHtml(t)}">${escapeHtml(t)}</div>`).join("")}
      </div>
      ` : ""}
      <div class="card">
        <div class="list-compact">
          ${filtered.length === 0 ? emptyState("No events match", "") :
            filtered.slice(0, 1000).map(e => {
              const ts = e.ts ? new Date(e.ts * 1000).toISOString().replace("T", " ").slice(0, 19) : "—";
              const dataJson = e.data && Object.keys(e.data).length > 0 ? JSON.stringify(e.data, null, 2) : null;
              return `
                <div class="log-detail-row">
                  <div class="log-ts">${ts}</div>
                  <div class="log-type">${escapeHtml(e.type || "?")}</div>
                  <div class="log-vm-tag">${escapeHtml(e.vm_id || "")}</div>
                  <div class="log-severity ${e.severity || "INFO"}">${e.severity || "INFO"}</div>
                  <div class="log-msg">
                    ${escapeHtml(e.message || "")}
                    ${dataJson ? `<pre class="log-json">${escapeHtml(dataJson)}</pre>` : ""}
                  </div>
                </div>
              `;
            }).join("")
          }
        </div>
      </div>
    </div>
  `;
  document.querySelectorAll("[data-vm-filter]").forEach(el => el.addEventListener("click", () => store.set({ logFilter: { ...store.state.logFilter, vm: el.dataset.vmFilter } })));
  document.querySelectorAll("[data-sev-filter]").forEach(el => el.addEventListener("click", () => store.set({ logFilter: { ...store.state.logFilter, severity: el.dataset.sevFilter } })));
  document.querySelectorAll("[data-type-filter]").forEach(el => el.addEventListener("click", () => store.set({ logFilter: { ...store.state.logFilter, type: el.dataset.typeFilter } })));
  document.querySelectorAll(".log-detail-row").forEach(row => {
    row.addEventListener("click", () => row.classList.toggle("expanded"));
  });
}

/* ============================================================
   CONFIG EDITOR
   ============================================================ */
const CONFIG_SCHEMA = {
  general: {
    icon: "⚙", title: "General", desc: "VM identity and instrument",
    fields: [
      { path: "vm_id", label: "VM ID", type: "text", readonly: true },
      { path: "display_name", label: "Display Name", type: "text" },
      { path: "symbol", label: "Symbol", type: "text", desc: "Broker's symbol (e.g. USTEC)" },
      { path: "cost_per_lot", label: "Cost / Lot", type: "number", step: 0.01, desc: "Round-trip cost per lot ($)" },
    ],
  },
  risk: {
    icon: "💰", title: "Risk", desc: "Position sizing and safety limits",
    fields: [
      { path: "risk.risk_mode", label: "Risk Mode", type: "select", options: ["starting_balance", "current_balance"] },
      { path: "risk.starting_balance", label: "Starting Balance", type: "number", step: 1000 },
      { path: "risk.risk_pct", label: "Risk %", type: "number", step: 0.05, min: 0.01, max: 5.0 },
      { path: "risk.max_lots", label: "Max Lots", type: "number", step: 0.01 },
      { path: "risk.min_lot", label: "Min Lot", type: "number", step: 0.01 },
      { path: "risk.lot_step", label: "Lot Step", type: "number", step: 0.01 },
      { path: "risk.max_daily_loss_usd", label: "Daily DD Limit ($)", type: "number", step: 100 },
      { path: "risk.auto_halt_on_daily_loss", label: "Auto Halt on Daily DD", type: "bool" },
    ],
  },
  mt5: {
    icon: "📡", title: "MT5", desc: "MT5 connection",
    fields: [
      { path: "mt5.path", label: "MT5 Path", type: "text", desc: "Leave empty for auto-detect" },
      { path: "mt5.timeout_ms", label: "Timeout (ms)", type: "number", step: 1000 },
    ],
  },
};

let configDraft = null;
let configOriginal = null;
let configActiveTab = "general";

function getByPath(obj, path) {
  const parts = path.split(".");
  let cur = obj;
  for (const p of parts) {
    if (cur == null) return undefined;
    cur = cur[p];
  }
  return cur;
}
function setByPath(obj, path, val) {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (!(parts[i] in cur)) cur[parts[i]] = {};
    cur = cur[parts[i]];
  }
  cur[parts[parts.length - 1]] = val;
}
function computeConfigDiff() {
  const changes = {};
  if (!configOriginal || !configDraft) return changes;
  const walk = (a, b, prefix = "") => {
    const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
    for (const k of keys) {
      const path = prefix ? prefix + "." + k : k;
      const av = a?.[k], bv = b?.[k];
      if (typeof av === "object" && av && !Array.isArray(av) && typeof bv === "object" && bv && !Array.isArray(bv)) walk(av, bv, path);
      else if (JSON.stringify(av) !== JSON.stringify(bv)) changes[path] = { old: av, new: bv };
    }
  };
  walk(configOriginal, configDraft);
  return changes;
}

function renderConfig() {
  const vms = Object.values(store.state.vms);
  if (vms.length === 0) {
    document.getElementById("main").innerHTML = `<div class="page">${emptyState("No VMs", "Wait for VM")}</div>`;
    return;
  }
  if (!store.state.selectedVm) store.state.selectedVm = vms[0].vm_id;
  const vm = store.state.vms[store.state.selectedVm];
  if (!vm) return;

  if (!configOriginal || configOriginal.vm_id !== vm.vm_id) {
    configOriginal = JSON.parse(JSON.stringify(vm.config || {}));
    configDraft = JSON.parse(JSON.stringify(vm.config || {}));
  }
  const diff = computeConfigDiff();
  const dirty = Object.keys(diff).length > 0;

  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Configuration</div>
          <div class="page-subtitle">${escapeHtml(vm.vm_id)} · ${dirty ? Object.keys(diff).length + ' change(s)' : 'no changes'}</div>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          ${vmSelectorHTML(store.state.selectedVm)}
          <button class="btn" id="cfg-reset" ${dirty ? '' : 'disabled'}>Reset</button>
          <button class="btn primary" id="cfg-push" ${dirty ? '' : 'disabled'}>Push</button>
        </div>
      </div>
      ${dirty ? renderDiffPanel(diff) : ''}
      <div class="config-editor">
        <div class="config-tabs">
          ${Object.entries(CONFIG_SCHEMA).map(([key, spec]) => `
            <div class="config-tab ${configActiveTab === key ? 'active' : ''}" data-tab="${key}">
              <span class="config-tab-icon">${spec.icon}</span>
              <span>${spec.title}</span>
            </div>
          `).join("")}
        </div>
        <div class="config-panel">
          ${renderConfigPanel(configActiveTab, diff)}
        </div>
      </div>
    </div>
  `;

  document.querySelectorAll(".config-tab").forEach(el => el.addEventListener("click", () => { configActiveTab = el.dataset.tab; renderConfig(); }));
  document.querySelectorAll("[data-field-path]").forEach(el => {
    const handler = (e) => {
      const path = e.target.dataset.fieldPath;
      const type = e.target.dataset.fieldType;
      let val;
      if (type === "bool") val = e.target.checked;
      else if (type === "number") val = e.target.value === "" ? null : Number(e.target.value);
      else val = e.target.value;
      setByPath(configDraft, path, val);
      renderConfig();
    };
    el.addEventListener("input", handler);
    el.addEventListener("change", handler);
  });
  document.getElementById("cfg-reset")?.addEventListener("click", () => {
    configDraft = JSON.parse(JSON.stringify(configOriginal));
    renderConfig();
  });
  document.getElementById("cfg-push")?.addEventListener("click", () => {
    const reason = prompt("Reason?", "manual edit");
    if (reason === null) return;
    ws.send(JSON.stringify({ type: "command", action: "push_config", vm_id: vm.vm_id, config: configDraft, reason }));
    toast("Sending…", "info");
  });
  bindVmSelector("config");
}

function renderConfigPanel(tabKey, diff) {
  const spec = CONFIG_SCHEMA[tabKey];
  return `
    <div class="config-panel-title">${spec.icon} ${spec.title}</div>
    <div class="config-panel-desc">${spec.desc}</div>
    ${spec.fields.map(f => renderConfigField(f, diff)).join("")}
  `;
}

function renderConfigField(f, diff) {
  const val = getByPath(configDraft, f.path);
  const dirty = f.path in diff ? "dirty" : "";
  let input;
  if (f.type === "bool") {
    input = `<input type="checkbox" class="config-checkbox ${dirty}" data-field-path="${f.path}" data-field-type="bool" ${val ? 'checked' : ''} ${f.readonly ? 'disabled' : ''}>`;
  } else if (f.type === "select") {
    input = `<select class="config-select ${dirty}" data-field-path="${f.path}" data-field-type="select">
      ${f.options.map(o => `<option value="${o}" ${val === o ? 'selected' : ''}>${o}</option>`).join("")}
    </select>`;
  } else if (f.type === "number") {
    input = `<input type="number" class="config-field-input ${dirty}" data-field-path="${f.path}" data-field-type="number" value="${val ?? ''}" step="${f.step ?? 1}" ${f.min != null ? `min="${f.min}"` : ""} ${f.max != null ? `max="${f.max}"` : ""} ${f.readonly ? 'readonly' : ''}>`;
  } else {
    input = `<input type="text" class="config-field-input ${dirty}" data-field-path="${f.path}" data-field-type="text" value="${escapeHtml(val ?? '')}" ${f.readonly ? 'readonly' : ''}>`;
  }
  return `
    <div class="config-field">
      <div class="config-field-label">
        <div class="config-field-name">${escapeHtml(f.label)}</div>
        ${f.desc ? `<div class="config-field-desc">${escapeHtml(f.desc)}</div>` : ''}
      </div>
      ${input}
    </div>
  `;
}

function renderDiffPanel(diff) {
  return `
    <div class="config-diff-panel">
      <div class="config-diff-title">⚠️ Pending changes (${Object.keys(diff).length})</div>
      ${Object.entries(diff).map(([path, ch]) => `
        <div class="config-diff-row">
          <span class="config-diff-key">${escapeHtml(path)}</span>
          <span class="config-diff-old">${escapeHtml(JSON.stringify(ch.old))}</span>
          <span class="config-diff-new">→ ${escapeHtml(JSON.stringify(ch.new))}</span>
        </div>
      `).join("")}
    </div>
  `;
}

/* ============================================================
   DETAIL PANEL
   ============================================================ */
function focusTrade(vmId, tradeId) {
  const vm = store.state.vms[vmId];
  if (!vm) return;
  const trade = vm.trades.find(t => String(t.trade_id) === String(tradeId));
  if (!trade) return;
  openDetail(trade, vm);
}

function openDetail(trade, vm) {
  const panel = document.getElementById("detail-panel");
  const body = document.getElementById("detail-body");
  const title = document.getElementById("detail-title");
  const dir = trade.direction === 1 ? "LONG" : "SHORT";
  const pnl = trade.realized_pnl || 0;
  const closed = trade.exit_ts != null;
  const isWin = pnl > 0;
  title.textContent = `Trade #${String(trade.trade_id).slice(0, 12)}`;
  body.innerHTML = `
    <div class="detail-section">
      <div class="detail-section-title">Overview</div>
      <div class="detail-row"><span class="k">VM</span><span class="v">${escapeHtml(vm.vm_id)}</span></div>
      <div class="detail-row"><span class="k">Direction</span><span class="v ${dir === 'LONG' ? 'pos' : 'neg'}">${dir}</span></div>
      <div class="detail-row"><span class="k">Status</span><span class="v ${closed ? (isWin ? 'pos' : 'neg') : ''}">${closed ? (isWin ? 'WIN' : 'LOSS') : 'OPEN'}</span></div>
      <div class="detail-row"><span class="k">Symbol</span><span class="v">${escapeHtml(trade.symbol || vm.symbol || '?')}</span></div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Times</div>
      <div class="detail-row"><span class="k">Entry</span><span class="v small">${fmtTime(trade.entry_ts)}</span></div>
      <div class="detail-row"><span class="k">Exit</span><span class="v small">${fmtTime(trade.exit_ts)}</span></div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Prices</div>
      <div class="detail-row"><span class="k">Entry</span><span class="v">${(trade.entry_price || 0).toFixed(2)}</span></div>
      <div class="detail-row"><span class="k">Exit</span><span class="v">${(trade.exit_price || 0).toFixed(2)}</span></div>
      <div class="detail-row"><span class="k">SL</span><span class="v neg">${(trade.sl_price || 0).toFixed(2)}</span></div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">P&amp;L</div>
      <div class="detail-row"><span class="k">Realized PnL</span><span class="v ${pnlClass(pnl)}">${closed ? pnlSign(pnl) + fmt$(pnl) : '—'}</span></div>
      <div class="detail-row"><span class="k">Lots</span><span class="v">${(trade.lots || 0).toFixed(2)}</span></div>
      <div class="detail-row"><span class="k">MT5 Ticket</span><span class="v">${trade.mt5_ticket || '?'}</span></div>
      ${trade.exit_reason ? `<div class="detail-row"><span class="k">Exit Reason</span><span class="v">${escapeHtml(trade.exit_reason)}</span></div>` : ''}
    </div>
  `;
  panel.classList.add("open");
  panel.setAttribute("aria-hidden", "false");
}

function closeDetail() {
  document.getElementById("detail-panel").classList.remove("open");
  document.getElementById("detail-panel").setAttribute("aria-hidden", "true");
}

/* ============================================================
   COMMAND PALETTE
   ============================================================ */
const cmdkCommands = [
  { label: "Go to Dashboard", route: "overview", hint: "1" },
  { label: "Go to Live Chart", route: "live", hint: "2" },
  { label: "Go to Trades", route: "trades", hint: "3" },
  { label: "Go to Stats", route: "stats", hint: "4" },
  { label: "Go to Fleet", route: "fleet", hint: "5" },
  { label: "Go to Logs", route: "logs", hint: "7" },
  { label: "Go to Config", route: "config", hint: "8", requiresUnlock: true },
  { label: "Cycle Theme", action: cycleTheme, hint: "T" },
  { label: "Toggle Nav", action: toggleNav, hint: "\\" },
];
function openCmdK() {
  document.getElementById("cmdk").classList.add("open");
  const input = document.getElementById("cmdk-input");
  input.value = ""; renderCmdkResults(""); setTimeout(() => input.focus(), 10);
}
function closeCmdK() { document.getElementById("cmdk").classList.remove("open"); }
function renderCmdkResults(query) {
  const q = query.toLowerCase().trim();
  const results = [];
  for (const c of cmdkCommands) {
    if (c.requiresUnlock && !UNLOCK.unlocked) continue;
    if (!q || c.label.toLowerCase().includes(q)) results.push(c);
  }
  for (const vid of Object.keys(store.state.vms)) {
    if (!q || vid.toLowerCase().includes(q)) {
      results.push({ label: `VM: ${vid}`, action: () => { store.set({ selectedVm: vid }); navigate("live/" + vid); }, hint: "vm" });
    }
  }
  const container = document.getElementById("cmdk-results");
  if (results.length === 0) { container.innerHTML = `<div class="cmdk-empty">No results</div>`; return; }
  container.innerHTML = results.slice(0, 20).map((r, i) => `
    <div class="cmdk-item ${i === 0 ? 'focused' : ''}" data-idx="${i}">
      <span class="cmdk-item-label">${escapeHtml(r.label)}</span>
      <span class="cmdk-item-hint">${escapeHtml(r.hint || "")}</span>
    </div>
  `).join("");
  container.querySelectorAll(".cmdk-item").forEach((el, i) => {
    el.addEventListener("click", () => {
      const r = results[i];
      if (r.route) navigate(r.route);
      if (r.action) r.action();
      closeCmdK();
    });
  });
}

/* ============================================================
   NAV / TOPBAR / THEME MENU / STATUS
   ============================================================ */
function toggleNav() {
  const app = document.getElementById("app");
  const expanded = !app.classList.contains("nav-expanded");
  app.classList.toggle("nav-expanded", expanded);
  localStorage.setItem("jg-nav-expanded", expanded);
}
function updateNavActive(route) {
  document.querySelectorAll(".nav-item[data-route]").forEach(el => el.classList.toggle("active", el.dataset.route === route));
}
function updateTopBarStats() {
  const t = fleetOverallStats();
  const balEl = document.getElementById("stat-balance");
  const pnlEl = document.getElementById("stat-total-pnl");
  const posEl = document.getElementById("stat-positions");
  const vmsEl = document.getElementById("stat-vms");
  if (balEl) balEl.textContent = fmt$(t.totalBalance, 0);
  if (pnlEl) {
    pnlEl.textContent = pnlSign(t.totalPnl) + fmt$(t.totalPnl, 0);
    pnlEl.className = "tb-stat-value " + pnlClass(t.totalPnl);
  }
  if (posEl) posEl.textContent = t.positions;
  if (vmsEl) vmsEl.textContent = `${t.connected}/${t.vmCount}`;
}
function updateConnectionStatus() {
  const el = document.getElementById("live-status");
  if (!el) return;
  const c = store.state.connected;
  el.className = "status-badge " + (c ? "connected" : "disconnected");
  el.innerHTML = c ? "<span>LIVE</span>" : "<span>reconnecting…</span>";
}
function initThemeMenu() {
  const btn = document.getElementById("theme-btn");
  const menu = document.getElementById("theme-menu");
  btn.addEventListener("click", (e) => { e.stopPropagation(); menu.classList.toggle("open"); });
  document.addEventListener("click", (e) => {
    if (!menu.contains(e.target) && !btn.contains(e.target)) menu.classList.remove("open");
  });
  menu.querySelectorAll("[data-theme]").forEach(opt => {
    opt.addEventListener("click", () => {
      applyTheme(opt.dataset.theme);
      store.set({ theme: opt.dataset.theme });
      menu.classList.remove("open");
    });
  });
}

/* ============================================================
   ROUTE RENDER
   ============================================================ */
function renderCurrentRoute() {
  const route = store.state.route;
  if (route === "config" && !UNLOCK.unlocked) { navigate("overview"); return; }
  updateNavActive(route);
  if (route !== "live" && charts.live) {
    try { charts.live.chart.remove(); } catch {}
    charts.live = null;
  }
  if (route !== "overview" && charts.equity) {
    try { charts.equity.destroy(); } catch {}
    charts.equity = null;
  }
  const routes = { overview: renderOverview, live: renderLive, trades: renderTrades, stats: renderStats, fleet: renderFleet, logs: renderLogs, config: renderConfig };
  (routes[route] || renderOverview)();
  if (!UNLOCK.unlocked) hideConfigNav();
}

/* ============================================================
   INIT
   ============================================================ */
function init() {
  applyTheme(store.state.theme);
  if (store.state.navExpanded) document.getElementById("app").classList.add("nav-expanded");

  document.querySelectorAll(".nav-item[data-route]").forEach(item => {
    item.addEventListener("click", (e) => { e.preventDefault(); navigate(item.dataset.route); });
  });
  document.getElementById("nav-toggle").addEventListener("click", toggleNav);
  document.getElementById("search-trigger").addEventListener("click", openCmdK);
  document.getElementById("detail-close").addEventListener("click", closeDetail);
  document.getElementById("cmdk-input").addEventListener("input", (e) => renderCmdkResults(e.target.value));
  document.querySelectorAll("[data-cmdk-close]").forEach(el => el.addEventListener("click", closeCmdK));

  initThemeMenu();

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); openCmdK(); return; }
    if (document.getElementById("cmdk").classList.contains("open")) {
      if (e.key === "Escape") closeCmdK();
      return;
    }
    if (e.target.tagName === "INPUT") return;
    const routeMap = { "1": "overview", "2": "live", "3": "trades", "4": "stats", "5": "fleet", "7": "logs", "8": "config" };
    if (routeMap[e.key]) {
      if (routeMap[e.key] === "config" && !UNLOCK.unlocked) return;
      navigate(routeMap[e.key]);
    }
    if (e.key === "t" || e.key === "T") cycleTheme();
    if (e.key === "\\") toggleNav();
    if (e.key === "Escape") { closeDetail(); document.getElementById("theme-menu").classList.remove("open"); }
  });

  store.subscribe(() => {
    updateTopBarStats();
    updateConnectionStatus();
    renderCurrentRoute();
  });

  const { route, params } = parseRoute();
  if (params[0]) store.set({ selectedVm: params[0] });
  store.set({ route });

  setInterval(() => { if (store.state.route === "live") updateSessionBadge(); }, 30000);

  initUnlockPattern();
  connectWS();
}

document.addEventListener("DOMContentLoaded", init);