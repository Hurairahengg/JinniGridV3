/* ============================================================
   PRIVACY / CONFIG UNLOCK SYSTEM
   ============================================================ */
const UNLOCK = {
  // SHA-256 hash of the actual password. GENERATE YOUR OWN.
  // In browser console: (async()=>{const h=await crypto.subtle.digest("SHA-256",new TextEncoder().encode("YOUR_PWD"));console.log(Array.from(new Uint8Array(h)).map(b=>b.toString(16).padStart(2,"0")).join(""))})()
  correctHash: "d6e1ba5ffc9cedb66266c42cc04a2f03eb794e11ac4e3e2f55e1f4f9779e3fc7",
  logoClicks: 0,
  themeClicks: 0,
  submitClicksEmpty: 0,
  stage: 0,
  resetTimer: null,
  unlocked: sessionStorage.getItem("jg-config-unlocked") === "1",
};

async function sha256(text) {
  // Use native crypto.subtle if available (secure contexts)
  if (window.crypto && window.crypto.subtle) {
    try {
      const buf = new TextEncoder().encode(text);
      const hash = await crypto.subtle.digest("SHA-256", buf);
      return Array.from(new Uint8Array(hash))
        .map(b => b.toString(16).padStart(2, "0")).join("");
    } catch (e) {
      // Fall through to JS implementation
    }
  }
  return sha256JS(text);
}

// Pure JS SHA-256 fallback for insecure contexts (plain HTTP)
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
  const K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];
  const H = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
  ];

  // UTF-8 encode
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
    let [a, b, c, d, e, f, g, h] = H;
    for (let i = 0; i < 64; i++) {
      const S1 = rr(6, e) ^ rr(11, e) ^ rr(25, e);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[i] + w[i]) | 0;
      const S0 = rr(2, a) ^ rr(13, a) ^ rr(22, a);
      const mj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + mj) | 0;
      h = g; g = f; f = e; e = (d + t1) | 0;
      d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0;
    H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0;
    H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0;
    H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
  }
  return H.map(toHex).join("");
}

function resetUnlockSequence() {
  UNLOCK.logoClicks = 0;
  UNLOCK.themeClicks = 0;
  UNLOCK.submitClicksEmpty = 0;
  UNLOCK.stage = 0;
  clearTimeout(UNLOCK.resetTimer);
  const modal = document.getElementById("unlock-modal");
  if (modal) modal.remove();
}

function armResetTimer() {
  clearTimeout(UNLOCK.resetTimer);
  UNLOCK.resetTimer = setTimeout(() => {
    if (UNLOCK.stage > 0 && UNLOCK.stage < 5) resetUnlockSequence();
  }, 8000);
}

function hideConfigNav() {
  if (UNLOCK.unlocked) return;
  document.querySelectorAll('[data-route="config"]').forEach(el => {
    el.style.display = "none";
  });
}

function revealConfigNav() {
  document.querySelectorAll('[data-route="config"]').forEach(el => {
    el.style.display = "";
  });
}

function showUnlockModal() {
  const existing = document.getElementById("unlock-modal");
  if (existing) existing.remove();

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
          input.value = "";
          input.placeholder = "real password";
          input.focus();
        }
      } else {
        resetUnlockSequence();
        modal.remove();
      }
      return;
    }

    if (UNLOCK.stage === 4) {
      if (!val) {
        toast("Password required", "error", 2000);
        return;
      }
      const hash = await sha256(val);
      if (hash === UNLOCK.correctHash) {
        UNLOCK.stage = 5;
        UNLOCK.unlocked = true;
        sessionStorage.setItem("jg-config-unlocked", "1");
        revealConfigNav();
        modal.remove();
        toast("✅ Config unlocked", "success");
      } else {
        input.value = "";
        toast("Access denied", "error", 2000);
        setTimeout(() => {
          resetUnlockSequence();
          modal.remove();
        }, 800);
      }
    }
  });

  cancelBtn.addEventListener("click", () => {
    resetUnlockSequence();
    modal.remove();
  });

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
        if (UNLOCK.logoClicks >= 4) {
          UNLOCK.stage = 1;
          UNLOCK.logoClicks = 0;
        }
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
          UNLOCK.stage = 3;
          UNLOCK.themeClicks = 0;
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
    selectedVm: null,
    selectedTrade: null,
    route: "overview",
    theme: localStorage.getItem("jg-theme") || "dark",
    navExpanded: localStorage.getItem("jg-nav-expanded") === "true",
    connected: false,
    tradeFilter: "all",
    tradeTimeframe: "all",
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
function fmtNum(v, decimals = 2) {
  if (v == null || isNaN(v)) return "—";
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
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
  const d = new Date(sec * 1000);
  return d.toISOString().replace("T", " ").slice(0, 16) + "Z";
}
function timeAgo(sec) {
  if (!sec) return "—";
  const diff = Date.now() / 1000 - sec;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
function getCSSVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function vmSelectorHTML(currentVm, onChangeAction) {
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
  const sel = document.getElementById("vm-selector");
  if (!sel) return;
  sel.addEventListener("change", () => {
    const vid = sel.value;
    if (!vid) return;
    store.set({ selectedVm: vid });
    if (routeName === "config") {
      configOriginal = null;
      configDraft = null;
    }
    navigate(routeName + "/" + vid);
  });
}

/* Aggregations */
function fleetTotals() {
  const vms = Object.values(store.state.vms);
  let bal = 0, todayPnl = 0, todayTrades = 0, todayWins = 0, positions = 0, connected = 0;
  const now = Date.now() / 1000;
  const dayStart = Math.floor(now / 86400) * 86400;
  for (const v of vms) {
    bal += v.balance || 0;
    positions += v.position_count || 0;
    if (v.status === "online" || v.status === "trading") connected++;
    for (const t of (v.trades || [])) {
      if (t.exit_ts && t.entry_ts >= dayStart) {
        todayTrades++;
        const pnl = t.pnl_dollars_net || 0;
        todayPnl += pnl;
        if (pnl > 0) todayWins++;
      }
    }
  }
  return {
    totalBalance: bal, todayPnl, todayTrades,
    todayWR: todayTrades > 0 ? (todayWins / todayTrades * 100) : 0,
    positions, connected, vmCount: vms.length,
  };
}

function vmMetrics(vm) {
  const closed = (vm.trades || []).filter(t => t.exit_ts);
  const n = closed.length;
  const wins = closed.filter(t => (t.pnl_dollars_net || 0) > 0).length;
  const wr = n > 0 ? (wins / n * 100) : 0;
  const net = closed.reduce((s, t) => s + (t.pnl_dollars_net || 0), 0);
  const wSum = closed.filter(t => (t.pnl_dollars_net || 0) > 0).reduce((s, t) => s + t.pnl_dollars_net, 0);
  const lSum = closed.filter(t => (t.pnl_dollars_net || 0) < 0).reduce((s, t) => s + t.pnl_dollars_net, 0);
  const pf = lSum < 0 ? (wSum / Math.abs(lSum)) : (wSum > 0 ? Infinity : 0);
  const now = Date.now() / 1000;
  const dayStart = Math.floor(now / 86400) * 86400;
  const today = closed.filter(t => t.entry_ts >= dayStart);
  const todayNet = today.reduce((s, t) => s + (t.pnl_dollars_net || 0), 0);
  return { n, wins, wr, net, pf, today: today.length, todayNet };
}

/* Canvas drawing */
function drawSparkline(canvas, values, color) {
  if (!canvas || !values || values.length < 2) return;
  // Use canvas's OWN bounding rect (CSS-sized) not parent's
  const rect = canvas.getBoundingClientRect();
  const w = Math.floor(rect.width);
  const h = Math.floor(rect.height);
  if (w < 10 || h < 10) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  for (let i = 0; i < values.length; i++) {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((values[i] - min) / range) * (h - 4) - 2;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function drawAreaChart(canvas, values, color) {
  if (!canvas || !values || values.length < 2) return;
  const rect = canvas.getBoundingClientRect();
  const w = Math.floor(rect.width);
  const h = Math.floor(rect.height);
  if (w < 10 || h < 10) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, color + "66");
  grad.addColorStop(1, color + "00");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.moveTo(0, h);
  for (let i = 0; i < values.length; i++) {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((values[i] - min) / range) * (h - 24) - 12;
    ctx.lineTo(x, y);
  }
  ctx.lineTo(w, h);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  for (let i = 0; i < values.length; i++) {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((values[i] - min) / range) * (h - 24) - 12;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function drawAreaChart(canvas, values, color) {
  if (!canvas || !values || values.length < 2) return;
  const parent = canvas.parentElement;
  if (!parent) return;
  const rect = parent.getBoundingClientRect();
  const w = Math.floor(rect.width);
  const h = Math.floor(rect.height);
  if (w < 10 || h < 10) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, color + "66");
  grad.addColorStop(1, color + "00");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.moveTo(0, h);
  for (let i = 0; i < values.length; i++) {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((values[i] - min) / range) * (h - 24) - 12;
    ctx.lineTo(x, y);
  }
  ctx.lineTo(w, h);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  for (let i = 0; i < values.length; i++) {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((values[i] - min) / range) * (h - 24) - 12;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

/* HMA calc */
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
   ROUTER
   ============================================================ */
function navigate(route) {
  window.location.hash = "#/" + route;
}
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
    glass: "#0a0f1e", light: "#ffffff", paper: "#faf7f2", mint: "#f0fdf6",
    sunset: "#1a0a1f"
  };
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", themeColorMap[theme] || "#08090c");
  if (charts.live) rebuildLiveChart();
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
        ...old,
        ...inc,
        // Preserve local state when incoming payload has 0/null
        balance: inc.balance || old.balance || 0,
        equity: inc.equity || old.equity || 0,
        peak_balance: inc.peak_balance || old.peak_balance || 0,
        trades: inc.trades && inc.trades.length ? inc.trades : (old.trades || []),
        events: inc.events && inc.events.length ? inc.events : (old.events || []),
        equity_history: inc.equity_history && inc.equity_history.length ? inc.equity_history : (old.equity_history || []),
        bars: old.bars || inc.bars || [],   // prefer live bars over stale DB reload
      };
    }
    // Keep any local-only VMs that aren't in payload
    for (const vid in existing) {
      if (!(vid in merged)) merged[vid] = existing[vid];
    }

    const selected = store.state.selectedVm || Object.keys(merged)[0] || null;
    store.set({ vms: merged, selectedVm: selected });
    return;
  }
  if (t === "vm_event") {
    const vms = { ...store.state.vms };
    const vid = msg.vm_id;
    if (!vms[vid]) {
      vms[vid] = { vm_id: vid, trades: [], events: [], equity_history: [], bars: [], balance: 0, status: "online" };
    }
    const vm = { ...vms[vid] };
    const et = msg.event_type;
    const d = msg.data;

    if (et === "TRADE_OPEN") {
      const trade = {
        trade_id: d.trade_id, vm_id: vid, symbol: d.symbol, direction: d.direction,
        entry_ts: d.entry_brick.time, entry_price: d.entry_price, sl_price: d.sl_price,
        lots: d.lots, exit_ts: null, exit_price: null, pnl_dollars_net: null,
        main_ma_value: d.main_ma_value, fast_ma_value: d.fast_ma_value,
        main_slope_value: d.main_slope_value, fast_slope_value: d.fast_slope_value,
      };
      vm.trades = [...vm.trades, trade];
      toast(`📈 ${vid}: ${d.direction === 1 ? "LONG" : "SHORT"} @ ${d.entry_price.toFixed(2)}`, "success");
    } else if (et === "TRADE_CLOSE") {
      vm.trades = vm.trades.map(tr => tr.trade_id === d.trade_id ? {
        ...tr, exit_ts: d.exit_time, exit_price: d.exit_price,
        pnl_dollars_net: d.pnl_net, exit_reason: d.exit_reason,
        bars_held: d.bars_held, minutes_held: d.minutes_held,
      } : tr);
      const pnl = d.pnl_net || 0;
      toast(`${pnl > 0 ? "✅" : "🚨"} ${vid}: ${pnl > 0 ? "WIN" : "LOSS"} ${fmt$(pnl)}`, pnl > 0 ? "success" : "error");
    } else if (et === "HEARTBEAT") {
      vm.status = (d.current_state || "").toLowerCase();
      vm.mt5_connected = d.mt5_connected;
      vm.position_count = d.position_count;
      vm.today_trades = d.today_trades;
      vm.last_seen = Date.now() / 1000;
      // Update balance from heartbeat if provided
      if (d.balance) vm.balance = d.balance;
      if (d.equity) vm.equity = d.equity;
    } else if (et === "READY_TO_TRADE") {
      vm.status = "trading";
      vm.balance = d.mt5_balance || vm.balance;
      vm.equity = d.mt5_equity || vm.equity;
    } else if (et === "SESSION_START" || et === "SESSION_END") {
      vm.events = [...vm.events, { type: et, ts: d.start_time || d.end_time, severity: "INFO", message: et }];
    } else if (et === "ERROR" || et === "WARNING") {
      vm.events = [...vm.events, {
        type: et, ts: Date.now() / 1000, severity: et,
        message: d.error_message || d.message || "?",
      }];
    } else if (et === "CONFIG_UPDATED" || et === "CONFIG_APPLIED") {
      if (store.state.route === "config") {
        configOriginal = null;
        configDraft = null;
      }
      vm.events = [...vm.events, {
        type: et, ts: (msg.timestamp || Date.now()) / 1000, severity: "INFO",
        message: et === "CONFIG_UPDATED" ? "Config edited from dashboard" : "Config applied on VM",
        data: d,
      }];
    }
    vms[vid] = vm;
    store.set({ vms });
    return;
  }
  if (t === "bar_new") {
    const vms = { ...store.state.vms };
    const vm = vms[msg.vm_id];
    if (!vm) return;
    vm.bars = [...(vm.bars || []), msg.bar];
    if (vm.bars.length > 2000) vm.bars.shift();
    if (msg.vm_id === store.state.selectedVm && store.state.route === "live" && charts.live) {
      try {
        charts.live.series.update(msg.bar);
        updateLiveMAs();
      } catch {}
    }
    return;
  }
  if (t === "validation_result") {
    const vms = { ...store.state.vms };
    const vid = msg.vm_id;
    if (vms[vid]) {
      const vm = { ...vms[vid] };
      vm.trades = vm.trades.map(tr => tr.trade_id === msg.trade_id ? {
        ...tr, validation_status: msg.result.status,
        validation_confidence: msg.result.confidence,
        validation_details: msg.result.details
      } : tr);
      vms[vid] = vm;
      store.set({ vms });
    }
    return;
  }
  if (t === "toast") {
    toast(msg.message, msg.level || "info");
    return;
  }
  if (t === "config_result") {
    if (msg.ok) {
      toast(`✅ Config saved & pushed to ${msg.vm_id}`, "success");
      configOriginal = null;
      configDraft = null;
    } else {
      const errs = (msg.errors || []).join("; ") || "unknown";
      toast(`❌ Config rejected: ${errs}`, "error", 6000);
    }
    return;
  }
}

/* ============================================================
   VIEWS
   ============================================================ */
const charts = { live: null };

/* --- OVERVIEW --- */
function renderOverview() {
  const totals = fleetTotals();
  const vms = Object.values(store.state.vms);
  const allTrades = [];
  const allEvents = [];
  for (const v of vms) {
    for (const t of (v.trades || [])) allTrades.push({ ...t, vm_id: v.vm_id });
    for (const e of (v.events || [])) allEvents.push({ ...e, vm_id: v.vm_id });
  }
  allTrades.sort((a, b) => (b.entry_ts || 0) - (a.entry_ts || 0));
  allEvents.sort((a, b) => (b.ts || 0) - (a.ts || 0));

  const eqMap = new Map();
  for (const v of vms) {
    for (const eq of (v.equity_history || [])) {
      const bucket = Math.floor(eq.ts / 3600) * 3600;
      eqMap.set(bucket, (eqMap.get(bucket) || 0) + eq.balance);
    }
  }
  const fleetEqPoints = Array.from(eqMap.entries()).sort((a, b) => a[0] - b[0]);
  const fleetEqValues = fleetEqPoints.map(p => p[1]);

  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Overview</div>
          <div class="page-subtitle">Fleet command center</div>
        </div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">Total Balance</div>
          <div class="kpi-value">${fmt$(totals.totalBalance, 0)}</div>
          <div class="kpi-sub"><span>${totals.vmCount} VM${totals.vmCount !== 1 ? "s" : ""}</span></div>
          <canvas class="kpi-sparkline" id="spark-bal"></canvas>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Today PnL</div>
          <div class="kpi-value ${pnlClass(totals.todayPnl)}">${pnlSign(totals.todayPnl)}${fmt$(totals.todayPnl)}</div>
          <div class="kpi-sub"><span>${totals.todayTrades} trade${totals.todayTrades !== 1 ? "s" : ""}</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Today WR</div>
          <div class="kpi-value">${totals.todayTrades > 0 ? totals.todayWR.toFixed(1) + "%" : "—"}</div>
          <div class="kpi-sub"><span>${totals.todayTrades > 0 ? (totals.todayWR >= 20 ? "above 20% mark" : "below 20% mark") : "no trades yet"}</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Active Positions</div>
          <div class="kpi-value">${totals.positions}</div>
          <div class="kpi-sub"><span>${totals.connected} online</span></div>
        </div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">Fleet Equity</div>
              <div class="card-subtitle">Aggregated over time</div>
            </div>
          </div>
          <div class="card-body">
            <div class="chart-container short">
              <canvas id="fleet-eq-chart" style="width:100%;height:100%;"></canvas>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-header">
            <div class="card-title">VMs</div>
            <div class="card-subtitle">${vms.length} total</div>
          </div>
          <div class="list-compact list-scrollable">
            ${vms.length === 0 ? emptyState("No VMs connected", "Waiting for first VM to come online…") :
              vms.map(v => {
                const m = vmMetrics(v);
                const status = v.status || "unknown";
                return `
                  <div class="list-row node-row" data-vm="${escapeHtml(v.vm_id)}">
                    <span class="node-status-dot ${status}"></span>
                    <span class="node-name">${escapeHtml(v.vm_id)}</span>
                    <span class="node-balance">${fmt$(v.balance || 0, 0)}</span>
                    <span class="node-pnl ${pnlClass(m.todayNet)}">${pnlSign(m.todayNet)}${fmt$(m.todayNet, 0)}</span>
                  </div>
                `;
              }).join("")
            }
          </div>
        </div>
      </div>

      <div class="grid-2">
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
        <div class="card">
          <div class="card-header">
            <div class="card-title">Activity</div>
            <div class="card-subtitle">Last 50 events</div>
          </div>
          <div class="list-compact list-scrollable">
            ${allEvents.length === 0 ? emptyState("No activity yet", "") :
              allEvents.slice(0, 50).map(e => activityHTML(e)).join("")
            }
          </div>
        </div>
      </div>
    </div>
  `;

  requestAnimationFrame(() => requestAnimationFrame(() => {
    const accent = getCSSVar("--accent");
    const eqCanvas = document.getElementById("fleet-eq-chart");
    if (eqCanvas && fleetEqValues.length >= 2) {
      drawAreaChart(eqCanvas, fleetEqValues, accent);
    } else if (eqCanvas) {
      const ctx = eqCanvas.getContext("2d");
      const parent = eqCanvas.parentElement;
      const rect = parent.getBoundingClientRect();
      eqCanvas.width = rect.width;
      eqCanvas.height = rect.height;
      ctx.fillStyle = getCSSVar("--text-muted");
      ctx.font = "12px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText("Waiting for equity data…", rect.width / 2, rect.height / 2);
    }
    const sparkBal = document.getElementById("spark-bal");
    if (sparkBal) {
      const allBal = vms.reduce((arr, v) => arr.concat((v.equity_history || []).map(e => e.balance)), []);
      if (allBal.length >= 2) drawSparkline(sparkBal, allBal.slice(-20), accent);
    }
  }));

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

function tradeRowHTML(t, showVm = false) {
  const isWin = (t.pnl_dollars_net || 0) > 0;
  const dir = t.direction === 1 ? "LONG" : "SHORT";
  const pnl = t.pnl_dollars_net || 0;
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
    "TRADE_OPEN": { c: "trade", i: "▲" },
    "TRADE_CLOSE": { c: "trade", i: "◆" },
    "SESSION_START": { c: "session", i: "🌅" },
    "SESSION_END": { c: "session", i: "🌇" },
    "VM_ONLINE": { c: "info", i: "🚀" },
    "READY_TO_TRADE": { c: "info", i: "✓" },
    "ERROR": { c: "warn", i: "✕" },
    "WARNING": { c: "warn", i: "⚠" },
    "HALT": { c: "warn", i: "🛑" },
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

/* --- LIVE VIEW --- */
function renderLive() {
  const vm = store.state.vms[store.state.selectedVm];
  document.getElementById("main").innerHTML = `
    <div class="live-container">
      <div class="live-toolbar">
        <div class="card-title">Live · ${escapeHtml(store.state.selectedVm || 'no VM')}</div>
        <div style="margin-left:12px;">${vmSelectorHTML(store.state.selectedVm, "live")}</div>
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
        <div style="margin-left:auto;" class="flex gap-2">
          <span class="session-badge" id="session-badge">Session status…</span>
        </div>
      </div>
      <div class="live-chart-wrap" id="live-chart-wrap"></div>
    </div>
  `;
  if (!vm) return;
  setTimeout(() => { initLiveChart(vm); updateSessionBadge(); }, 30);
  document.getElementById("ma-main").addEventListener("change", updateLiveMAs);
  document.getElementById("ma-fast").addEventListener("change", updateLiveMAs);
  bindVmSelector("live");
}

function initLiveChart(vm) {
  const el = document.getElementById("live-chart-wrap");
  if (!el) return;

  // Show placeholder if no bars yet
  if (!vm.bars || vm.bars.length === 0) {
    el.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:center; height:100%; flex-direction:column; gap:12px; padding: var(--space-6);">
        <div style="font-size:40px; opacity:0.4;">📊</div>
        <div style="color:var(--text-dim); font-family:var(--font-mono); font-size:13px; font-weight:600;">
          Waiting for bars from ${escapeHtml(vm.vm_id)}…
        </div>
        <div style="color:var(--text-muted); font-size:11px; text-align:center; max-width:400px; line-height:1.5;">
          Bars stream in real-time as the VM forms them from live ticks.
          Historical warmup bars aren't shown here — only bars that formed since the dashboard connected.
        </div>
        <div style="margin-top:8px; padding:6px 12px; background:var(--bg-2); border:1px solid var(--border); border-radius:var(--radius); font-family:var(--font-mono); font-size:11px; color:var(--text-muted);">
          Status: <span style="color:var(--text);">${escapeHtml(vm.status || 'unknown')}</span>
        </div>
      </div>
    `;
    return;
  }

  const bg = getCSSVar("--bg-0");
  const text = getCSSVar("--text-dim");
  const grid = getCSSVar("--bg-2");
  const border = getCSSVar("--border");

  // Clear placeholder if it was showing
  el.innerHTML = "";

  const chart = LightweightCharts.createChart(el, {
    layout: {
      background: { type: "solid", color: bg },
      textColor: text,
      fontFamily: getComputedStyle(document.body).fontFamily,
      fontSize: 11
    },
    grid: {
      vertLines: { color: grid },
      horzLines: { color: grid }
    },
    timeScale: {
      borderColor: border,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 8
    },
    rightPriceScale: { borderColor: border },
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
    color: getCSSVar("--purple"),
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  });
  const fastMA = chart.addLineSeries({
    color: getCSSVar("--cyan"),
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  });

  charts.live = { chart, series, mainMA, fastMA };

  // Deduplicate bars by timestamp (Lightweight Charts requires strictly ascending times)
  const seenTimes = new Set();
  const cleanBars = [];
  for (const b of vm.bars) {
    if (!seenTimes.has(b.time)) {
      seenTimes.add(b.time);
      cleanBars.push(b);
    }
  }
  cleanBars.sort((a, b) => a.time - b.time);

  if (cleanBars.length > 0) {
    series.setData(cleanBars);
    updateLiveMAs();
  }

  // Trade markers
  const markers = [];
  for (const t of (vm.trades || [])) {
    if (!t.entry_ts) continue;
    markers.push({
      time: t.entry_ts,
      position: t.direction === 1 ? "belowBar" : "aboveBar",
      color: t.direction === 1 ? getCSSVar("--green") : getCSSVar("--red"),
      shape: t.direction === 1 ? "arrowUp" : "arrowDown",
      text: `#${String(t.trade_id).slice(0, 6)}`,
    });
    if (t.exit_ts) {
      const isWin = (t.pnl_dollars_net || 0) > 0;
      markers.push({
        time: t.exit_ts,
        position: "inBar",
        color: isWin ? getCSSVar("--green") : getCSSVar("--red"),
        shape: "square",
        text: isWin ? "W" : "L",
      });
    }
  }
  markers.sort((a, b) => a.time - b.time);
  const seenMarkerTimes = new Set();
  const uniqueMarkers = markers.filter(m => {
    let t = m.time;
    while (seenMarkerTimes.has(t)) t += 1;
    m.time = t;
    seenMarkerTimes.add(t);
    return true;
  });
  series.setMarkers(uniqueMarkers);

  try { chart.timeScale().fitContent(); } catch (e) {}

  // Resize handler (removes old ones to prevent stacking)
  if (charts.live._resizeHandler) {
    window.removeEventListener("resize", charts.live._resizeHandler);
  }
  charts.live._resizeHandler = () => {
    if (charts.live && charts.live.chart) {
      chart.applyOptions({
        width: el.clientWidth,
        height: el.clientHeight
      });
    }
  };
  window.addEventListener("resize", charts.live._resizeHandler);
}

function updateLiveMAs() {
  if (!charts.live) return;
  const vm = store.state.vms[store.state.selectedVm];
  if (!vm || !vm.bars || vm.bars.length < 30) return;
  const showMain = document.getElementById("ma-main")?.checked;
  const showFast = document.getElementById("ma-fast")?.checked;
  const closes = vm.bars.map(b => b.close);
  const mainVals = computeHMA(closes, 21);
  const fastVals = computeHMA(closes, 14);
  const mainData = [], fastData = [];
  for (let i = 0; i < vm.bars.length; i++) {
    if (mainVals[i] !== null) mainData.push({ time: vm.bars[i].time, value: mainVals[i] });
    if (fastVals[i] !== null) fastData.push({ time: vm.bars[i].time, value: fastVals[i] });
  }
  charts.live.mainMA.setData(showMain ? mainData : []);
  charts.live.fastMA.setData(showFast ? fastData : []);
}

function rebuildLiveChart() {
  if (charts.live) {
    try { charts.live.chart.remove(); } catch {}
    charts.live = null;
    const vm = store.state.vms[store.state.selectedVm];
    if (vm) initLiveChart(vm);
  }
}

function updateSessionBadge() {
  const el = document.getElementById("session-badge");
  if (!el) return;
  const now = new Date();
  const cstHour = (now.getUTCHours() - 6 + 24) % 24;
  const NY = new Set([8, 9, 10, 11, 12, 13, 14, 15, 16]);
  if (NY.has(cstHour)) {
    el.className = "session-badge active";
    el.textContent = `NY active · CST ${cstHour}:00`;
  } else {
    let h = 8 - cstHour; if (h <= 0) h += 24;
    el.className = "session-badge";
    el.textContent = `NY closed · opens in ${h}h`;
  }
}

/* --- TRADES --- */
function renderTrades() {
  const vms = Object.values(store.state.vms);
  const filter = store.state.tradeFilter;
  const tf = store.state.tradeTimeframe;

  let trades = [];
  for (const v of vms) for (const t of (v.trades || [])) trades.push({ ...t, vm_id: v.vm_id });
  trades.sort((a, b) => (b.entry_ts || 0) - (a.entry_ts || 0));

  const now = Date.now() / 1000;
  const dayStart = Math.floor(now / 86400) * 86400;
  const weekStart = dayStart - 7 * 86400;
  const monthStart = dayStart - 30 * 86400;
  if (tf === "today") trades = trades.filter(t => t.entry_ts >= dayStart);
  else if (tf === "week") trades = trades.filter(t => t.entry_ts >= weekStart);
  else if (tf === "month") trades = trades.filter(t => t.entry_ts >= monthStart);

  if (filter === "LONG") trades = trades.filter(t => t.direction === 1);
  else if (filter === "SHORT") trades = trades.filter(t => t.direction === -1);
  else if (filter === "WIN") trades = trades.filter(t => (t.pnl_dollars_net || 0) > 0);
  else if (filter === "LOSS") trades = trades.filter(t => (t.pnl_dollars_net || 0) <= 0);
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
          ${trades.length === 0 ? emptyState("No trades match filter", "Try different filters") :
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

/* --- STATS --- */
function renderStats() {
  const vms = Object.values(store.state.vms);
  if (vms.length === 0) {
    document.getElementById("main").innerHTML = `<div class="page">${emptyState("No VMs", "Waiting for connections")}</div>`;
    return;
  }
  if (!store.state.selectedVm) store.state.selectedVm = vms[0].vm_id;
  const vm = store.state.vms[store.state.selectedVm];
  if (!vm) {
    document.getElementById("main").innerHTML = `<div class="page">${emptyState("Select a VM", "Choose from the dropdown")}</div>`;
    return;
  }
  const m = vmMetrics(vm);
  const trades = (vm.trades || []).filter(t => t.exit_ts);
  const wSum = trades.filter(t => (t.pnl_dollars_net || 0) > 0).reduce((s, t) => s + t.pnl_dollars_net, 0);
  const lSum = trades.filter(t => (t.pnl_dollars_net || 0) < 0).reduce((s, t) => s + t.pnl_dollars_net, 0);
  const nWin = trades.filter(t => (t.pnl_dollars_net || 0) > 0).length;
  const nLoss = trades.filter(t => (t.pnl_dollars_net || 0) < 0).length;
  const avgWin = nWin > 0 ? wSum / nWin : 0;
  const avgLoss = nLoss > 0 ? lSum / nLoss : 0;
  const expectancy = m.n > 0 ? m.net / m.n : 0;
  const longs = trades.filter(t => t.direction === 1);
  const shorts = trades.filter(t => t.direction === -1);
  const longNet = longs.reduce((s, t) => s + (t.pnl_dollars_net || 0), 0);
  const shortNet = shorts.reduce((s, t) => s + (t.pnl_dollars_net || 0), 0);
  const bal = vm.balance || 0;
  const peak = vm.peak_balance || bal;
  const dd = bal - peak;

  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Statistics</div>
          <div class="page-subtitle">${escapeHtml(vm.vm_id)}</div>
        </div>
        <div>${vmSelectorHTML(store.state.selectedVm, "stats")}</div>
      </div>
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">Win Rate</div>
          <div class="kpi-value">${m.n > 0 ? m.wr.toFixed(1) + "%" : "—"}</div>
          <div class="kpi-sub"><span>${m.wins}W / ${m.n - m.wins}L</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Profit Factor</div>
          <div class="kpi-value">${isFinite(m.pf) && m.pf > 0 ? m.pf.toFixed(2) : "—"}</div>
          <div class="kpi-sub"><span>${m.pf >= 1.2 ? "deployable" : m.pf >= 1 ? "marginal" : "unprofitable"}</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Net PnL</div>
          <div class="kpi-value ${pnlClass(m.net)}">${pnlSign(m.net)}${fmt$(m.net, 0)}</div>
          <div class="kpi-sub"><span>${m.n} trades</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Drawdown</div>
          <div class="kpi-value ${dd < 0 ? 'neg' : ''}">${fmt$(dd, 0)}</div>
          <div class="kpi-sub"><span>Peak: ${fmt$(peak, 0)}</span></div>
        </div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-header"><div class="card-title">Equity Curve</div></div>
          <div class="card-body">
            <div class="chart-container">
              <canvas id="stat-eq" style="width:100%;height:100%"></canvas>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">Direction Split</div></div>
          <div class="card-body">
            <div class="detail-row"><span class="k">Long trades</span><span class="v">${longs.length}</span></div>
            <div class="detail-row"><span class="k">Long net</span><span class="v ${pnlClass(longNet)}">${pnlSign(longNet)}${fmt$(longNet)}</span></div>
            <div class="detail-row"><span class="k">Long WR</span><span class="v">${longs.length > 0 ? (longs.filter(t => (t.pnl_dollars_net || 0) > 0).length / longs.length * 100).toFixed(1) + "%" : "—"}</span></div>
            <div style="height:1px;background:var(--border);margin:12px 0"></div>
            <div class="detail-row"><span class="k">Short trades</span><span class="v">${shorts.length}</span></div>
            <div class="detail-row"><span class="k">Short net</span><span class="v ${pnlClass(shortNet)}">${pnlSign(shortNet)}${fmt$(shortNet)}</span></div>
            <div class="detail-row"><span class="k">Short WR</span><span class="v">${shorts.length > 0 ? (shorts.filter(t => (t.pnl_dollars_net || 0) > 0).length / shorts.length * 100).toFixed(1) + "%" : "—"}</span></div>
          </div>
        </div>
      </div>

      <div class="grid-3">
        <div class="card">
          <div class="card-header"><div class="card-title">Averages</div></div>
          <div class="card-body">
            <div class="detail-row"><span class="k">Avg win</span><span class="v pos">${fmt$(avgWin)}</span></div>
            <div class="detail-row"><span class="k">Avg loss</span><span class="v neg">${fmt$(avgLoss)}</span></div>
            <div class="detail-row"><span class="k">Expectancy</span><span class="v ${pnlClass(expectancy)}">${fmt$(expectancy)}</span></div>
            <div class="detail-row"><span class="k">Best</span><span class="v pos">${trades.length ? fmt$(Math.max(...trades.map(t => t.pnl_dollars_net || 0))) : "—"}</span></div>
            <div class="detail-row"><span class="k">Worst</span><span class="v neg">${trades.length ? fmt$(Math.min(...trades.map(t => t.pnl_dollars_net || 0))) : "—"}</span></div>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">Account</div></div>
          <div class="card-body">
            <div class="detail-row"><span class="k">Balance</span><span class="v">${fmt$(bal)}</span></div>
            <div class="detail-row"><span class="k">Equity</span><span class="v">${fmt$(vm.equity || bal)}</span></div>
            <div class="detail-row"><span class="k">Peak</span><span class="v">${fmt$(peak)}</span></div>
            <div class="detail-row"><span class="k">Status</span><span class="v">${escapeHtml(vm.status || "?")}</span></div>
            <div class="detail-row"><span class="k">Symbol</span><span class="v">${escapeHtml(vm.symbol || "?")}</span></div>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">Volume</div></div>
          <div class="card-body">
            <div class="detail-row"><span class="k">Total</span><span class="v">${m.n}</span></div>
            <div class="detail-row"><span class="k">Wins</span><span class="v pos">${m.wins}</span></div>
            <div class="detail-row"><span class="k">Losses</span><span class="v neg">${m.n - m.wins}</span></div>
            <div class="detail-row"><span class="k">Gross win</span><span class="v pos">${fmt$(wSum)}</span></div>
            <div class="detail-row"><span class="k">Gross loss</span><span class="v neg">${fmt$(lSum)}</span></div>
          </div>
        </div>
      </div>
    </div>
  `;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const c = document.getElementById("stat-eq");
    if (c && vm.equity_history && vm.equity_history.length > 1) {
      drawAreaChart(c, vm.equity_history.map(e => e.balance), getCSSVar("--accent"));
    }
  }));
  bindVmSelector("stats");
}

/* --- FLEET --- */
function renderFleet() {
  const vms = Object.values(store.state.vms);
  const t = fleetTotals();
  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Fleet</div>
          <div class="page-subtitle">${vms.length} VM${vms.length !== 1 ? "s" : ""} · ${fmt$(t.totalBalance, 0)}</div>
        </div>
      </div>
      <div class="node-grid">
        ${vms.length === 0 ? emptyState("No VMs", "Waiting for connections") :
          vms.map(v => {
            const m = vmMetrics(v);
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
                <canvas class="node-card-chart" id="chart-${escapeHtml(v.vm_id)}"></canvas>
                <div class="node-card-metrics">
                  <div class="node-card-metric">
                    <div class="lbl">Trades</div>
                    <div class="val">${m.n}</div>
                  </div>
                  <div class="node-card-metric">
                    <div class="lbl">Win%</div>
                    <div class="val">${m.n > 0 ? m.wr.toFixed(0) + "%" : "—"}</div>
                  </div>
                  <div class="node-card-metric">
                    <div class="lbl">Today</div>
                    <div class="val ${pnlClass(m.todayNet)}">${pnlSign(m.todayNet)}${fmt$(m.todayNet, 0)}</div>
                  </div>
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
  requestAnimationFrame(() => requestAnimationFrame(() => {
    for (const v of vms) {
      const c = document.getElementById(`chart-${v.vm_id}`);
      if (c && v.equity_history && v.equity_history.length > 1) {
        drawSparkline(c, v.equity_history.map(e => e.balance), getCSSVar("--accent"));
      }
    }
  }));
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

/* --- VALIDATION --- */
function renderValidation() {
  const vms = Object.values(store.state.vms);
  const allValidated = [];
  for (const v of vms) {
    for (const t of (v.trades || [])) {
      if (t.validation_status) allValidated.push({ ...t, vm_id: v.vm_id });
    }
  }
  allValidated.sort((a, b) => (b.entry_ts || 0) - (a.entry_ts || 0));

  const total = allValidated.length;
  const counts = allValidated.reduce((acc, t) => {
    acc[t.validation_status] = (acc[t.validation_status] || 0) + 1;
    return acc;
  }, {});
  const avgConf = total > 0 ? allValidated.reduce((s, t) => s + (t.validation_confidence || 0), 0) / total : 0;

  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Validation</div>
          <div class="page-subtitle">Independent verification of every VM trade</div>
        </div>
      </div>
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">Fleet Confidence</div>
          <div class="kpi-value">${avgConf.toFixed(1)}%</div>
          <div class="kpi-sub"><span>${total} validated</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Exact Match</div>
          <div class="kpi-value pos">${counts["EXACT_MATCH"] || 0}</div>
          <div class="kpi-sub"><span>${total > 0 ? ((counts["EXACT_MATCH"] || 0) / total * 100).toFixed(1) + "%" : "—"}</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Minor Mismatch</div>
          <div class="kpi-value">${counts["MINOR_MISMATCH"] || 0}</div>
          <div class="kpi-sub"><span>tolerated</span></div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Major / No Signal</div>
          <div class="kpi-value neg">${(counts["MAJOR_MISMATCH"] || 0) + (counts["NO_SIGNAL"] || 0)}</div>
          <div class="kpi-sub"><span>investigate</span></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">Recent Validations</div>
          <div class="card-subtitle">Last ${Math.min(100, allValidated.length)} · click for detail</div>
        </div>
        <div class="list-compact">
          ${allValidated.length === 0 ? emptyState("Nothing to validate yet", "Waiting for VM trades") :
            allValidated.slice(0, 100).map(t => `
              <div class="trade-row" data-tid="${escapeHtml(t.trade_id)}" data-vm="${escapeHtml(t.vm_id)}">
                <div class="trade-id">#${String(t.trade_id).slice(0, 8)}</div>
                <div class="badge ${t.validation_status}">${t.validation_status.split("_")[0]}</div>
                <div class="dir-arrow ${t.direction === 1 ? 'LONG' : 'SHORT'}">${t.direction === 1 ? '▲' : '▼'}</div>
                <div class="trade-time">${t.entry_ts ? new Date(t.entry_ts * 1000).toISOString().replace("T", " ").slice(0, 16) : "—"} · ${escapeHtml(t.vm_id)}</div>
                <div></div>
                <div class="trade-price">conf ${(t.validation_confidence || 0).toFixed(0)}%</div>
                <div class="trade-pnl ${pnlClass(t.pnl_dollars_net)}">${t.pnl_dollars_net != null ? pnlSign(t.pnl_dollars_net) + fmt$(t.pnl_dollars_net) : "—"}</div>
              </div>
            `).join("")
          }
        </div>
      </div>
    </div>
  `;
  document.querySelectorAll(".trade-row[data-tid]").forEach(row => {
    row.addEventListener("click", () => focusTrade(row.dataset.vm, row.dataset.tid));
  });
}

/* --- LOGS --- */
function renderLogs() {
  const vms = Object.values(store.state.vms);
  const filter = store.state.logFilter;
  const allEvents = [];
  for (const v of vms) {
    for (const e of (v.events || [])) allEvents.push({ ...e, vm_id: v.vm_id });
  }
  allEvents.sort((a, b) => (b.ts || 0) - (a.ts || 0));

  let filtered = allEvents;
  if (filter.vm !== "all") filtered = filtered.filter(e => e.vm_id === filter.vm);
  if (filter.severity !== "all") filtered = filtered.filter(e => (e.severity || "INFO") === filter.severity);

  const eventTypes = [...new Set(allEvents.map(e => e.type))].sort();
  if (filter.type && filter.type !== "all") {
    filtered = filtered.filter(e => e.type === filter.type);
  }

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
        ${["all", "INFO", "WARNING", "ERROR", "CRITICAL"].map(s =>
          `<div class="chip ${filter.severity === s ? 'active' : ''}" data-sev-filter="${s}">${s}</div>`
        ).join("")}
      </div>
      ${eventTypes.length > 0 ? `
      <div class="chip-row">
        <span style="font-size:11px; color:var(--text-muted); align-self:center;">Type:</span>
        <div class="chip ${!filter.type || filter.type === 'all' ? 'active' : ''}" data-type-filter="all">All types</div>
        ${eventTypes.slice(0, 15).map(t =>
          `<div class="chip ${filter.type === t ? 'active' : ''}" data-type-filter="${escapeHtml(t)}">${escapeHtml(t)}</div>`
        ).join("")}
      </div>
      ` : ""}

      <div class="card">
        <div class="list-compact">
          ${filtered.length === 0 ? emptyState("No events match filters", "") :
            filtered.slice(0, 1000).map((e, i) => {
              const ts = e.ts ? new Date(e.ts * 1000).toISOString().replace("T", " ").slice(0, 19) : "—";
              const dataJson = e.data && Object.keys(e.data).length > 0 ? JSON.stringify(e.data, null, 2) : null;
              const isConfigChange = e.type === "CONFIG_UPDATED";
              const configDiff = isConfigChange && e.data?.changes ? Object.keys(e.data.changes).map(k =>
                `<div>${escapeHtml(k)}: <span style="color:var(--red);">${escapeHtml(JSON.stringify(e.data.changes[k].old))}</span> → <span style="color:var(--green);">${escapeHtml(JSON.stringify(e.data.changes[k].new))}</span></div>`
              ).join("") : "";
              return `
                <div class="log-detail-row" data-log-idx="${i}">
                  <div class="log-ts">${ts}</div>
                  <div class="log-type">${escapeHtml(e.type || "?")}</div>
                  <div class="log-vm-tag">${escapeHtml(e.vm_id || "")}</div>
                  <div class="log-severity ${e.severity || "INFO"}">${e.severity || "INFO"}</div>
                  <div class="log-msg">
                    ${escapeHtml(e.message || "")}
                    ${configDiff ? `<div class="log-config-diff">${configDiff}</div>` : ""}
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

  document.querySelectorAll("[data-vm-filter]").forEach(el => {
    el.addEventListener("click", () => store.set({ logFilter: { ...store.state.logFilter, vm: el.dataset.vmFilter } }));
  });
  document.querySelectorAll("[data-sev-filter]").forEach(el => {
    el.addEventListener("click", () => store.set({ logFilter: { ...store.state.logFilter, severity: el.dataset.sevFilter } }));
  });
  document.querySelectorAll("[data-type-filter]").forEach(el => {
    el.addEventListener("click", () => store.set({ logFilter: { ...store.state.logFilter, type: el.dataset.typeFilter } }));
  });
  document.querySelectorAll(".log-detail-row").forEach(row => {
    row.addEventListener("click", (e) => {
      if (e.target.closest(".chip")) return;
      row.classList.toggle("expanded");
    });
  });
}

/* --- CONFIG EDITOR --- */
const CONFIG_SCHEMA = {
  general: {
    icon: "⚙", title: "General", desc: "VM identity and instrument",
    fields: [
      { path: "vm_id", label: "VM ID", type: "text", readonly: true, desc: "Cannot be changed" },
      { path: "display_name", label: "Display Name", type: "text", desc: "Shown in dashboard" },
      { path: "symbol", label: "Symbol", type: "text", desc: "MT5 symbol (e.g. USTEC, NAS100)" },
      { path: "brick_size", label: "Brick Size", type: "number", step: 0.1, desc: "Renko brick size in points" },
      { path: "price_decimals", label: "Price Decimals", type: "number", step: 1, desc: "Decimal places" },
      { path: "cost_per_lot", label: "Cost / Lot", type: "number", step: 0.01, desc: "Round-trip cost per lot ($)" },
    ],
  },
  risk: {
    icon: "💰", title: "Risk", desc: "Position sizing and safety limits",
    fields: [
      { path: "risk.risk_mode", label: "Risk Mode", type: "select",
        options: ["starting_balance", "current_balance"],
        desc: "Fixed % of starting balance (prop firm) or compound on current balance" },
      { path: "risk.starting_balance", label: "Starting Balance", type: "number", step: 1000, desc: "Used when risk_mode = starting_balance" },
      { path: "risk.risk_pct", label: "Risk %", type: "number", step: 0.05, min: 0.01, max: 5.0, desc: "% per trade (0.01–5.0)" },
      { path: "risk.max_lots", label: "Max Lots", type: "number", step: 0.01, max: 1000, desc: "Hard cap on position size" },
      { path: "risk.min_lot", label: "Min Lot", type: "number", step: 0.01 },
      { path: "risk.lot_step", label: "Lot Step", type: "number", step: 0.01 },
      { path: "risk.max_daily_loss_usd", label: "Daily DD Limit ($)", type: "number", step: 100, desc: "Auto-halt trigger" },
      { path: "risk.auto_halt_on_daily_loss", label: "Auto Halt on Daily DD", type: "bool" },
      { path: "risk.max_open_positions", label: "Max Open Positions", type: "number", step: 1 },
    ],
  },
  session: {
    icon: "🕐", title: "Session", desc: "Trading hours and days",
    fields: [
      { path: "session.timezone", label: "Timezone", type: "text", desc: "e.g. CST" },
      { path: "session.start_hour", label: "Start Hour", type: "number", step: 1, min: 0, max: 23 },
      { path: "session.end_hour", label: "End Hour", type: "number", step: 1, min: 0, max: 23 },
      { path: "session.days", label: "Days", type: "days", desc: "Days of week to trade" },
    ],
  },
  mt5: {
    icon: "📡", title: "MT5", desc: "MT5 connection settings",
    fields: [
      { path: "mt5.path", label: "MT5 Path", type: "text", nullable: true, desc: "Leave empty for auto-detect" },
      { path: "mt5.timeout_ms", label: "Timeout (ms)", type: "number", step: 1000 },
    ],
  },
  data: {
    icon: "📊", title: "Data", desc: "Warmup and memory settings",
    fields: [
      { path: "data.warmup_days", label: "Warmup Days", type: "number", step: 1, min: 1, max: 30, desc: "Historical tick days for warmup" },
      { path: "data.bars_in_memory", label: "Bars in Memory", type: "number", step: 100, desc: "Buffer size for rolling bars" },
    ],
  },
};

let configDraft = null;
let configOriginal = null;
let configActiveTab = "general";

function getValueByPath(obj, path) {
  const parts = path.split(".");
  let cur = obj;
  for (const p of parts) {
    if (cur == null) return undefined;
    cur = cur[p];
  }
  return cur;
}

function setValueByPath(obj, path, value) {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (!(parts[i] in cur)) cur[parts[i]] = {};
    cur = cur[parts[i]];
  }
  cur[parts[parts.length - 1]] = value;
}

function computeConfigDiff() {
  const changes = {};
  if (!configOriginal || !configDraft) return changes;
  const walk = (a, b, prefix = "") => {
    const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
    for (const k of keys) {
      const path = prefix ? prefix + "." + k : k;
      const av = a?.[k];
      const bv = b?.[k];
      if (typeof av === "object" && av && !Array.isArray(av) &&
          typeof bv === "object" && bv && !Array.isArray(bv)) {
        walk(av, bv, path);
      } else if (JSON.stringify(av) !== JSON.stringify(bv)) {
        changes[path] = { old: av, new: bv };
      }
    }
  };
  walk(configOriginal, configDraft);
  return changes;
}

function renderConfig() {
  const vms = Object.values(store.state.vms);
  if (vms.length === 0) {
    document.getElementById("main").innerHTML = `
      <div class="page">
        <div class="page-header">
          <div>
            <div class="page-title">Configuration</div>
            <div class="page-subtitle">No VMs connected</div>
          </div>
        </div>
        ${emptyState("No VMs available", "Wait for a VM to connect first")}
      </div>
    `;
    return;
  }
  if (!store.state.selectedVm && vms.length > 0) {
    store.state.selectedVm = vms[0].vm_id;
  }
  const vm = store.state.vms[store.state.selectedVm];
  if (!vm) {
    document.getElementById("main").innerHTML = `
      <div class="page">
        <div class="page-header">
          <div>
            <div class="page-title">Configuration</div>
            <div class="page-subtitle">Pick a VM to edit</div>
          </div>
          ${vmSelectorHTML(store.state.selectedVm, "config")}
        </div>
      </div>
    `;
    bindVmSelector("config");
    return;
  }

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
          <div class="page-subtitle">${escapeHtml(vm.vm_id)} · ${dirty ? Object.keys(diff).length + ' unsaved change' + (Object.keys(diff).length !== 1 ? 's' : '') : 'no changes'}</div>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          ${vmSelectorHTML(store.state.selectedVm, "config")}
          <button class="btn" id="cfg-reset" ${dirty ? '' : 'disabled'}>Reset</button>
          <button class="btn primary" id="cfg-push" ${dirty ? '' : 'disabled'}>Push to VM</button>
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

  document.querySelectorAll(".config-tab").forEach(el => {
    el.addEventListener("click", () => {
      configActiveTab = el.dataset.tab;
      renderConfig();
    });
  });

  document.querySelectorAll("[data-field-path]").forEach(el => {
    const handler = (e) => {
      const target = e.target;
      const path = target.dataset.fieldPath;
      const type = target.dataset.fieldType;
      let val;
      if (type === "bool") val = target.checked;
      else if (type === "number") val = target.value === "" ? null : Number(target.value);
      else val = target.value;
      setValueByPath(configDraft, path, val);
      updateConfigDirtyState();
    };
    el.addEventListener("input", handler);
    el.addEventListener("change", handler);
  });

  document.querySelectorAll("[data-day]").forEach(el => {
    el.addEventListener("change", () => {
      const day = el.dataset.day;
      const current = getValueByPath(configDraft, "session.days") || [];
      let updated;
      if (el.checked && !current.includes(day)) updated = [...current, day];
      else updated = current.filter(d => d !== day);
      const order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
      updated.sort((a, b) => order.indexOf(a) - order.indexOf(b));
      setValueByPath(configDraft, "session.days", updated);
      updateConfigDirtyState();
    });
  });

  document.getElementById("cfg-reset")?.addEventListener("click", () => {
    configDraft = JSON.parse(JSON.stringify(configOriginal));
    renderConfig();
    toast("Reset to saved config", "info");
  });

  document.getElementById("cfg-push")?.addEventListener("click", () => {
    const currentDiff = computeConfigDiff();
    const changed = Object.keys(currentDiff).length;
    if (!changed) return;
    const reason = prompt(`Reason for these ${changed} change(s)?`, "manual edit");
    if (reason === null) return;
    ws.send(JSON.stringify({
      type: "command", action: "push_config",
      vm_id: vm.vm_id, config: configDraft, reason: reason || "manual edit"
    }));
    toast("Sending config to VM…", "info");
  });

  bindVmSelector("config");
}

function updateConfigDirtyState() {
  const diff = computeConfigDiff();
  const dirty = Object.keys(diff).length > 0;

  document.querySelectorAll("[data-field-path]").forEach(el => {
    const path = el.dataset.fieldPath;
    if (path in diff) el.classList.add("dirty");
    else el.classList.remove("dirty");
  });

  const subtitle = document.querySelector(".page-header .page-subtitle");
  if (subtitle) {
    const vm = store.state.vms[store.state.selectedVm];
    subtitle.textContent = `${vm.vm_id} · ${dirty ? Object.keys(diff).length + ' unsaved change' + (Object.keys(diff).length !== 1 ? 's' : '') : 'no changes'}`;
  }

  const resetBtn = document.getElementById("cfg-reset");
  const pushBtn = document.getElementById("cfg-push");
  if (resetBtn) resetBtn.disabled = !dirty;
  if (pushBtn) pushBtn.disabled = !dirty;

  const existingDiff = document.querySelector(".config-diff-panel");
  const pageEl = document.querySelector(".page");
  const editorEl = document.querySelector(".config-editor");
  if (existingDiff) existingDiff.remove();
  if (dirty && pageEl && editorEl) {
    const tmpDiv = document.createElement("div");
    tmpDiv.innerHTML = renderDiffPanel(diff);
    const newPanel = tmpDiv.firstElementChild;
    if (newPanel) pageEl.insertBefore(newPanel, editorEl);
  }
}

function renderConfigPanel(tabKey, diff) {
  const spec = CONFIG_SCHEMA[tabKey];
  if (!spec) return "";
  return `
    <div class="config-panel-title">${spec.icon} ${spec.title}</div>
    <div class="config-panel-desc">${spec.desc}</div>
    ${spec.fields.map(f => renderConfigField(f, diff)).join("")}
  `;
}

function renderConfigField(f, diff) {
  const val = getValueByPath(configDraft, f.path);
  const isDirty = f.path in diff;
  const dirtyClass = isDirty ? "dirty" : "";
  let input;

  if (f.type === "bool") {
    input = `<input type="checkbox" class="config-checkbox ${dirtyClass}"
                     data-field-path="${f.path}" data-field-type="bool"
                     ${val ? 'checked' : ''} ${f.readonly ? 'disabled' : ''}>`;
  } else if (f.type === "select") {
    input = `<select class="config-select ${dirtyClass}"
                     data-field-path="${f.path}" data-field-type="select">
      ${f.options.map(o => `<option value="${o}" ${val === o ? 'selected' : ''}>${o}</option>`).join("")}
    </select>`;
  } else if (f.type === "days") {
    const arr = val || [];
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    input = `<div style="display:flex; flex-wrap: wrap; gap: 6px;">
      ${days.map(d => `
        <label style="display:flex; align-items:center; gap:4px; font-size:11px;">
          <input type="checkbox" class="config-checkbox" data-day="${d}" ${arr.includes(d) ? 'checked' : ''}>
          <span>${d}</span>
        </label>
      `).join("")}
    </div>`;
  } else if (f.type === "number") {
    const step = f.step ?? 1;
    const min = f.min != null ? `min="${f.min}"` : "";
    const max = f.max != null ? `max="${f.max}"` : "";
    input = `<input type="number" class="config-field-input ${dirtyClass}"
                     data-field-path="${f.path}" data-field-type="number"
                     value="${val ?? ''}" step="${step}" ${min} ${max}
                     ${f.readonly ? 'readonly' : ''}>`;
  } else {
    input = `<input type="text" class="config-field-input ${dirtyClass}"
                     data-field-path="${f.path}" data-field-type="text"
                     value="${escapeHtml(val ?? '')}"
                     ${f.readonly ? 'readonly' : ''}>`;
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
  const rows = Object.entries(diff).map(([path, change]) => `
    <div class="config-diff-row">
      <span class="config-diff-key">${escapeHtml(path)}</span>
      <span class="config-diff-old">${escapeHtml(JSON.stringify(change.old))}</span>
      <span class="config-diff-new">→ ${escapeHtml(JSON.stringify(change.new))}</span>
    </div>
  `).join("");
  return `
    <div class="config-diff-panel">
      <div class="config-diff-title">⚠️ Pending changes (${Object.keys(diff).length})</div>
      ${rows}
    </div>
  `;
}

function highlightJSON(s) {
  return escapeHtml(s)
    .replace(/(&quot;)([\w_]+)(&quot;)(:)/g, '<span class="json-key">$1$2$3</span>$4')
    .replace(/: (&quot;[^&]*&quot;)/g, ': <span class="json-string">$1</span>')
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="json-number">$1</span>')
    .replace(/: (true|false|null)/g, ': <span class="json-bool">$1</span>');
}

/* --- DEPLOY --- */
function renderDeploy() {
  document.getElementById("main").innerHTML = `
    <div class="page">
      <div class="page-header">
        <div>
          <div class="page-title">Deploy New VM</div>
          <div class="page-subtitle">Configure a new VM's strategy and risk</div>
        </div>
      </div>
      <div class="card">
        <div class="card-body">
          <p class="text-dim" style="font-size:13px;margin-bottom:16px">
            To onboard a new VM:
          </p>
          <ol style="color:var(--text-dim);font-size:13px;line-height:2;padding-left:24px">
            <li>Provision Windows VM with MT5 terminal installed and logged in</li>
            <li>Copy the <code style="background:var(--bg-2);padding:2px 6px;border-radius:3px;font-family:var(--font-mono)">vm/</code> folder to it</li>
            <li>Set environment variables: <code>MOTHER_HOST</code>, <code>MOTHER_PORT</code>, <code>VM_ID</code>, <code>SHARED_SECRET</code></li>
            <li>Run <code style="background:var(--bg-2);padding:2px 6px;border-radius:3px;font-family:var(--font-mono)">python vm/main.py</code></li>
            <li>VM appears here in "awaiting_config" state</li>
            <li>Copy an example config and adjust for the new VM</li>
            <li>Save as <code>mother/configs/&lt;vm_id&gt;.json</code></li>
            <li>Restart mother OR push config via dashboard</li>
          </ol>
          <div style="margin-top:24px;padding:16px;background:var(--bg-2);border-radius:8px;font-family:var(--font-mono);font-size:12px">
            <div class="text-muted" style="margin-bottom:8px">Quick command reference:</div>
            <div>set MOTHER_HOST=192.168.1.100</div>
            <div>set MOTHER_PORT=8765</div>
            <div>set VM_ID=vm2</div>
            <div>set SHARED_SECRET=your_secret</div>
            <div>python main.py</div>
          </div>
        </div>
      </div>
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
  store.set({ selectedTrade: { vmId, tradeId } });
  openDetail(trade, vm);
}

function openDetail(trade, vm) {
  const panel = document.getElementById("detail-panel");
  const body = document.getElementById("detail-body");
  const title = document.getElementById("detail-title");
  const isWin = (trade.pnl_dollars_net || 0) > 0;
  const dir = trade.direction === 1 ? "LONG" : "SHORT";
  const pnl = trade.pnl_dollars_net || 0;
  const closed = trade.exit_ts != null;
  title.textContent = `Trade #${String(trade.trade_id).slice(0, 12)}`;

  const validation = trade.validation_status ? `
    <div class="detail-section">
      <div class="detail-section-title">Validation</div>
      <div class="detail-row"><span class="k">Status</span><span class="v"><span class="badge ${trade.validation_status}">${trade.validation_status}</span></span></div>
      <div class="detail-row"><span class="k">Confidence</span><span class="v">${(trade.validation_confidence || 0).toFixed(1)}%</span></div>
      ${trade.validation_details && trade.validation_details.checks ? Object.entries(trade.validation_details.checks).map(([k, ok]) => `
        <div class="detail-row"><span class="k">${escapeHtml(k)}</span><span class="v ${ok ? 'pos' : 'neg'}">${ok ? '✓' : '✗'}</span></div>
      `).join("") : ""}
    </div>
  ` : "";

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
      <div class="detail-row"><span class="k">Entry</span><span class="v" style="font-size:10px">${fmtTime(trade.entry_ts)}</span></div>
      <div class="detail-row"><span class="k">Exit</span><span class="v" style="font-size:10px">${fmtTime(trade.exit_ts)}</span></div>
      <div class="detail-row"><span class="k">Bars held</span><span class="v">${trade.bars_held ?? '—'}</span></div>
      <div class="detail-row"><span class="k">Minutes</span><span class="v">${trade.minutes_held ? trade.minutes_held.toFixed(1) : '—'}</span></div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Prices</div>
      <div class="detail-row"><span class="k">Entry</span><span class="v">${(trade.entry_price || 0).toFixed(2)}</span></div>
      <div class="detail-row"><span class="k">Exit</span><span class="v">${(trade.exit_price || 0).toFixed(2)}</span></div>
      <div class="detail-row"><span class="k">SL</span><span class="v neg">${(trade.sl_price || 0).toFixed(2)}</span></div>
      <div class="detail-row"><span class="k">SL distance</span><span class="v">${(trade.sl_distance_pts || 0).toFixed(2)} pts</span></div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Indicators @ Entry</div>
      <div class="detail-row"><span class="k">Main HMA</span><span class="v">${trade.main_ma_value != null ? trade.main_ma_value.toFixed(2) : '—'}</span></div>
      <div class="detail-row"><span class="k">Fast HMA</span><span class="v">${trade.fast_ma_value != null ? trade.fast_ma_value.toFixed(2) : '—'}</span></div>
      <div class="detail-row"><span class="k">Main slope</span><span class="v">${trade.main_slope_value != null ? trade.main_slope_value.toFixed(3) + '%' : '—'}</span></div>
      <div class="detail-row"><span class="k">Fast slope</span><span class="v">${trade.fast_slope_value != null ? trade.fast_slope_value.toFixed(3) + '%' : '—'}</span></div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">P&amp;L</div>
      <div class="detail-row"><span class="k">Points</span><span class="v ${pnlClass(pnl)}">${(trade.pnl_points || 0).toFixed(2)}</span></div>
      <div class="detail-row"><span class="k">Gross</span><span class="v ${pnlClass(pnl)}">${trade.pnl_dollars_gross != null ? (trade.pnl_dollars_gross >= 0 ? '+' : '') + fmt$(trade.pnl_dollars_gross) : '—'}</span></div>
      <div class="detail-row"><span class="k">Cost</span><span class="v">${fmt$(trade.cost_dollars || trade.cost || 0)}</span></div>
      <div class="detail-row"><span class="k">Net</span><span class="v ${pnlClass(pnl)}">${closed ? pnlSign(pnl) + fmt$(pnl) : '—'}</span></div>
      <div class="detail-row"><span class="k">Lots</span><span class="v">${(trade.lots || 0).toFixed(2)}</span></div>
    </div>
    ${validation}
  `;
  panel.classList.add("open");
  panel.setAttribute("aria-hidden", "false");
}

function closeDetail() {
  document.getElementById("detail-panel").classList.remove("open");
  document.getElementById("detail-panel").setAttribute("aria-hidden", "true");
  store.set({ selectedTrade: null });
}

/* ============================================================
   COMMAND PALETTE
   ============================================================ */
const cmdkCommands = [
  { label: "Go to Overview", route: "overview", hint: "1" },
  { label: "Go to Live Chart", route: "live", hint: "2" },
  { label: "Go to Trades", route: "trades", hint: "3" },
  { label: "Go to Stats", route: "stats", hint: "4" },
  { label: "Go to Fleet", route: "fleet", hint: "5" },
  { label: "Go to Validation", route: "validation", hint: "6" },
  { label: "Go to Logs", route: "logs", hint: "7" },
  { label: "Go to Config", route: "config", hint: "8", requiresUnlock: true },
  { label: "Go to Deploy", route: "deploy", hint: "9" },
  { label: "Cycle Theme", action: cycleTheme, hint: "T" },
  { label: "Toggle Nav", action: toggleNav, hint: "\\" },
];

function openCmdK() {
  document.getElementById("cmdk").classList.add("open");
  const input = document.getElementById("cmdk-input");
  input.value = "";
  renderCmdkResults("");
  setTimeout(() => input.focus(), 10);
}
function closeCmdK() {
  document.getElementById("cmdk").classList.remove("open");
}

function renderCmdkResults(query) {
  const q = query.toLowerCase().trim();
  const results = [];
  for (const c of cmdkCommands) {
    if (c.requiresUnlock && !UNLOCK.unlocked) continue;
    if (!q || c.label.toLowerCase().includes(q)) results.push(c);
  }
  for (const vid of Object.keys(store.state.vms)) {
    if (!q || vid.toLowerCase().includes(q)) {
      results.push({
        label: `VM: ${vid}`,
        action: () => { store.set({ selectedVm: vid }); navigate("live/" + vid); },
        hint: "vm",
      });
    }
  }
  if (q.startsWith("halt ")) {
    const vid = q.slice(5).trim();
    if (store.state.vms[vid]) {
      results.unshift({ label: `Halt VM ${vid}`, action: () => sendCommand("halt", vid), hint: "cmd" });
    }
  }
  if (q.startsWith("resume ")) {
    const vid = q.slice(7).trim();
    if (store.state.vms[vid]) {
      results.unshift({ label: `Resume VM ${vid}`, action: () => sendCommand("resume", vid), hint: "cmd" });
    }
  }
  if (q.length >= 4) {
    for (const vid in store.state.vms) {
      const t = store.state.vms[vid].trades?.find(t => String(t.trade_id).includes(q));
      if (t) {
        results.push({
          label: `Trade #${String(t.trade_id).slice(0, 12)} on ${vid}`,
          action: () => focusTrade(vid, t.trade_id),
          hint: "trade",
        });
      }
    }
  }

  const container = document.getElementById("cmdk-results");
  if (results.length === 0) {
    container.innerHTML = `<div class="cmdk-empty">No results</div>`;
    return;
  }
  container.innerHTML = results.slice(0, 20).map((r, i) => `
    <div class="cmdk-item ${i === 0 ? 'focused' : ''}" data-idx="${i}">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
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
   NAV
   ============================================================ */
function toggleNav() {
  const app = document.getElementById("app");
  const expanded = !app.classList.contains("nav-expanded");
  app.classList.toggle("nav-expanded", expanded);
  localStorage.setItem("jg-nav-expanded", expanded);
  store.set({ navExpanded: expanded });
}
function updateNavActive(route) {
  document.querySelectorAll(".nav-item[data-route]").forEach(el => {
    el.classList.toggle("active", el.dataset.route === route);
  });
}

/* ============================================================
   TOP BAR STATS
   ============================================================ */
function updateTopBarStats() {
  const t = fleetTotals();
  const balEl = document.getElementById("stat-balance");
  const todayEl = document.getElementById("stat-today");
  const posEl = document.getElementById("stat-positions");
  const vmsEl = document.getElementById("stat-vms");
  if (balEl) {
    balEl.textContent = fmt$(t.totalBalance, 0);
    animatePulse(balEl);
  }
  if (todayEl) {
    todayEl.textContent = pnlSign(t.todayPnl) + fmt$(t.todayPnl, 0);
    todayEl.className = "tb-stat-value " + pnlClass(t.todayPnl);
    animatePulse(todayEl);
  }
  if (posEl) posEl.textContent = t.positions;
  if (vmsEl) vmsEl.textContent = `${t.connected}/${t.vmCount}`;
}
let pulseTimers = new WeakMap();
function animatePulse(el) {
  clearTimeout(pulseTimers.get(el));
  el.classList.remove("pulse");
  void el.offsetWidth;
  el.classList.add("pulse");
  pulseTimers.set(el, setTimeout(() => el.classList.remove("pulse"), 600));
}

function updateConnectionStatus() {
  const el = document.getElementById("live-status");
  if (!el) return;
  const c = store.state.connected;
  el.className = "status-badge " + (c ? "connected" : "disconnected");
  el.innerHTML = c ? "<span>LIVE</span>" : "<span>reconnecting…</span>";
}

/* ============================================================
   THEME MENU
   ============================================================ */
function initThemeMenu() {
  const btn = document.getElementById("theme-btn");
  const menu = document.getElementById("theme-menu");
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.classList.toggle("open");
  });
  document.addEventListener("click", (e) => {
    if (!menu.contains(e.target) && !btn.contains(e.target)) menu.classList.remove("open");
  });
  menu.querySelectorAll("[data-theme]").forEach(opt => {
    opt.addEventListener("click", () => {
      const t = opt.dataset.theme;
      applyTheme(t);
      store.set({ theme: t });
      menu.classList.remove("open");
      toast(`Theme: ${t}`, "info", 1500);
    });
  });
  updateThemeMenuActive();
}
function updateThemeMenuActive() {
  document.querySelectorAll("[data-theme]").forEach(el => {
    el.classList.toggle("active", el.dataset.theme === store.state.theme);
  });
}

/* ============================================================
   RENDER ROUTE
   ============================================================ */
function renderCurrentRoute() {
  const route = store.state.route;

  // Block Config route if not unlocked
  if (route === "config" && !UNLOCK.unlocked) {
    navigate("overview");
    return;
  }

  updateNavActive(route);
  if (route !== "live" && charts.live) {
    try { charts.live.chart.remove(); } catch {}
    charts.live = null;
  }
  const routes = {
    overview: renderOverview,
    live: renderLive,
    trades: renderTrades,
    stats: renderStats,
    fleet: renderFleet,
    validation: renderValidation,
    logs: renderLogs,
    config: renderConfig,
    deploy: renderDeploy,
  };
  const fn = routes[route] || renderOverview;
  fn();

  // Re-hide config nav after every re-render (in case DOM was rebuilt)
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
    item.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navigate(item.dataset.route); }
    });
  });
  document.getElementById("nav-toggle").addEventListener("click", toggleNav);
  document.getElementById("search-trigger").addEventListener("click", openCmdK);
  document.getElementById("search-trigger").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") openCmdK();
  });
  document.getElementById("detail-close").addEventListener("click", closeDetail);
  document.getElementById("cmdk-input").addEventListener("input", (e) => renderCmdkResults(e.target.value));
  document.querySelectorAll("[data-cmdk-close]").forEach(el => el.addEventListener("click", closeCmdK));

  initThemeMenu();

  // Keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault(); openCmdK(); return;
    }
    if (document.getElementById("cmdk").classList.contains("open")) {
      if (e.key === "Escape") closeCmdK();
      return;
    }
    if (e.target.tagName === "INPUT") return;
    const routeMap = { "1": "overview", "2": "live", "3": "trades", "4": "stats", "5": "fleet", "6": "validation", "7": "logs", "8": "config", "9": "deploy" };
    if (routeMap[e.key]) {
      // Block config keyboard shortcut when locked
      if (routeMap[e.key] === "config" && !UNLOCK.unlocked) return;
      navigate(routeMap[e.key]);
    }
    if (e.key === "t" || e.key === "T") cycleTheme();
    if (e.key === "\\") toggleNav();
    if (e.key === "Escape") {
      closeDetail();
      document.getElementById("theme-menu").classList.remove("open");
    }
  });

  store.subscribe(() => {
    updateTopBarStats();
    updateConnectionStatus();
    updateThemeMenuActive();
    renderCurrentRoute();
  });

  const { route, params } = parseRoute();
  if (params[0]) store.set({ selectedVm: params[0] });
  store.set({ route });

  setInterval(() => { if (store.state.route === "live") updateSessionBadge(); }, 30000);

  // Redraw charts on resize
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const route = store.state.route;
      if (route === "overview" || route === "fleet" || route === "stats") {
        renderCurrentRoute();
      }
    }, 200);
  });

  // Initialize the unlock pattern AFTER all UI is bound
  initUnlockPattern();

  connectWS();
}

document.addEventListener("DOMContentLoaded", init);
