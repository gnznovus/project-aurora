LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Aurora Login</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: radial-gradient(1200px 600px at 20% 0%, #1b1d54, transparent 65%), #090a24;
      font-family: "Segoe UI", "Trebuchet MS", sans-serif;
      color: #eef2ff;
    }
    .box {
      width: min(460px, 92vw);
      background: linear-gradient(180deg, #252a62, #1f2355);
      border: 1px solid #3a3f7a;
      border-radius: 14px;
      padding: 18px;
    }
    h1 { margin: 0 0 10px; font-size: 22px; }
    p { margin: 0 0 16px; color: #aeb7dc; font-size: 14px; }
    input, button {
      width: 100%;
      border-radius: 10px;
      border: 1px solid #3a3f7a;
      background: #12153d;
      color: #eef2ff;
      padding: 11px 12px;
      font-size: 14px;
      margin-bottom: 10px;
    }
    button { cursor: pointer; background: #30439f; font-weight: 700; }
    .err { color: #ff8a9a; font-size: 13px; min-height: 16px; }
  </style>
</head>
<body>
  <div class="box">
    <h1>Aurora Control Dashboard</h1>
    <p>Sign in to access dashboard data.</p>
    <input id="username" type="text" placeholder="Username" value="superadmin" />
    <input id="password" type="password" placeholder="Password" />
    <button id="login">Sign In</button>
    <div id="error" class="err"></div>
  </div>
  <script>
    document.getElementById("login").addEventListener("click", async () => {
      const username = document.getElementById("username").value;
      const password = document.getElementById("password").value;
      const errorEl = document.getElementById("error");
      errorEl.textContent = "";
      const res = await fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        errorEl.textContent = "Invalid credentials.";
        return;
      }
      const data = await res.json();
      window.location.href = data.redirect_to || "/dashboard";
    });
  </script>
</body>
</html>
"""


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Aurora Dashboard</title>
  <style>
    :root {
      --bg: #0f1032;
      --bg-2: #141644;
      --card: #212457;
      --card-2: #2b2e66;
      --line: #363a73;
      --text: #ecf1ff;
      --muted: #aeb7dc;
      --cyan: #48cbff;
      --amber: #e2c84e;
      --green: #64db66;
      --red: #ff6f7f;
      --warn: #ff9359;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(900px 520px at 0% 0%, #1e2155 0%, transparent 65%),
        radial-gradient(1000px 560px at 100% 0%, #1a1d4e 0%, transparent 70%),
        linear-gradient(180deg, var(--bg) 0%, #0b0c27 100%);
      color: var(--text);
      font-family: "Segoe UI", "Trebuchet MS", sans-serif;
    }
    .shell {
      padding: 14px 18px 16px;
      width: 100%;
      margin: 0;
    }
    .head {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 10px;
      margin-bottom: 12px;
    }
    .tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .tab-btn {
      border-radius: 10px;
      border: 1px solid var(--line);
      background: rgba(17, 20, 57, 0.85);
      color: var(--text);
      padding: 8px 12px;
      font-size: 13px;
      cursor: pointer;
    }
    .tab-btn.active {
      background: #3a4ea9;
      border-color: #4f64c7;
    }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }
    .title-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    input, button {
      border-radius: 10px;
      border: 1px solid var(--line);
      background: rgba(17, 20, 57, 0.85);
      color: var(--text);
      padding: 10px 12px;
      font-size: 14px;
    }
    button {
      cursor: pointer;
      background: #2b3678;
      font-weight: 700;
      transition: filter 120ms ease, transform 80ms ease, opacity 120ms ease;
    }
    button:hover { filter: brightness(1.08); }
    button:active { transform: translateY(1px); }
    button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
      transform: none;
    }
    .grid-top {
      display: grid;
      grid-template-columns: 1.4fr 1fr 1fr 1fr 1.4fr;
      gap: 10px;
      margin-bottom: 10px;
    }
    .grid-bottom {
      display: grid;
      grid-template-columns: 2fr 1.6fr 1.2fr;
      gap: 10px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: linear-gradient(180deg, rgba(47, 52, 108, 0.9), rgba(31, 35, 83, 0.95));
      padding: 12px;
      min-height: 118px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }
    .title { margin: 0 0 8px; color: var(--muted); font-size: 14px; font-weight: 600; letter-spacing: 0.2px; }
    .big { font-size: 64px; font-weight: 700; line-height: 0.92; margin: 4px 0 6px; }
    .unit { color: var(--muted); font-size: 24px; }
    .sub { color: var(--muted); font-size: 17px; margin-top: 2px; }
    .metric { font-size: 54px; font-weight: 700; line-height: 1; margin-top: 24px; }
    .metric .pct { font-size: 36px; color: var(--muted); }
    .status-row { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--line); display: flex; justify-content: space-between; color: var(--muted); font-size: 15px; }
    .panel { min-height: 365px; }
    .table { width: 100%; border-collapse: collapse; font-size: 15px; }
    .table th, .table td { padding: 7px 4px; border-bottom: 1px solid rgba(104, 112, 175, 0.25); text-align: left; }
    .table th { color: var(--muted); font-size: 12px; letter-spacing: 0.4px; }
    .table thead th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: #26295f;
    }
    .status-completed { color: var(--green); }
    .status-failed, .status-timeout { color: var(--red); }
    .status-queued, .status-leased { color: var(--warn); }
    .mini { font-size: 12px; color: var(--muted); }
    .mono { font-family: Consolas, "Courier New", monospace; font-size: 12px; }
    .line-wrap { height: 280px; position: relative; }
    .line-legend { position: absolute; right: 0; top: 0; font-size: 13px; color: var(--muted); }
    .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
    .muted { color: var(--muted); }
    .no-data { color: var(--muted); font-size: 14px; margin-top: 16px; }
    .progress-wrap { margin-top: 8px; width: 100%; height: 8px; border-radius: 999px; background: #10122f; overflow: hidden; }
    .progress-fill { height: 100%; background: linear-gradient(90deg, #44c0ff, #6fd67d); }
    .kpi-emph { border-color: rgba(255, 116, 137, 0.75); background: linear-gradient(180deg, rgba(71, 54, 102, 0.6), rgba(58, 44, 87, 0.6)); }
    .log-stream {
      height: 308px;
      overflow: hidden;
      border-top: 1px solid rgba(104, 112, 175, 0.25);
      margin-top: 8px;
      padding-top: 6px;
    }
    .log-line {
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      color: #d8e0ff;
      padding: 6px 0;
      border-bottom: 1px solid rgba(104, 112, 175, 0.18);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .login-banner {
      display: none;
      border: 1px solid #5b2d42;
      background: rgba(78, 37, 58, 0.55);
      color: #ffd8e1;
      padding: 8px 10px;
      border-radius: 9px;
      margin-bottom: 8px;
      font-size: 13px;
    }
    .superadmin {
      display: block;
      margin-top: 10px;
      border: 1px solid #4a3a78;
      background: linear-gradient(180deg, rgba(55, 42, 94, 0.7), rgba(39, 31, 76, 0.75));
      border-radius: 10px;
      padding: 12px;
    }
    .superadmin-grid {
      display: grid;
      grid-template-columns: 1fr 1.5fr;
      gap: 10px;
      margin-top: 8px;
    }
    .sa-title { margin: 0; color: #d9d5ff; font-size: 16px; }
    .sa-form input, .sa-form select, .sa-form button {
      width: 100%;
      margin-bottom: 8px;
      border-radius: 8px;
      border: 1px solid #62579a;
      background: rgba(26, 20, 54, 0.82);
      color: #f1ecff;
      padding: 9px 10px;
    }
    .sa-form button { cursor: pointer; background: #4a3aa6; font-weight: 700; }
    .sa-msg { min-height: 16px; font-size: 12px; color: #c4bfff; margin-top: 4px; }
    .sa-msg.ok { color: #8af6b6; }
    .sa-msg.err { color: #ff9aa8; }
    .sa-msg.busy { color: #ffd183; }
    .sa-actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 8px; }
    .sa-actions button { width: 100%; }
    .sa-kv { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }
    .sa-pill {
      border: 1px solid #5f4f94;
      border-radius: 8px;
      background: rgba(26, 20, 54, 0.62);
      padding: 8px;
      font-size: 12px;
      color: #d6cdf7;
    }
    .sa-backup-table { max-height: 220px; overflow: auto; border: 1px solid rgba(103, 91, 163, 0.35); border-radius: 8px; }
    .sa-box {
      border: 1px solid rgba(103, 91, 163, 0.35);
      background: rgba(28, 22, 57, 0.52);
      border-radius: 10px;
      padding: 10px;
      min-height: 180px;
    }
    .sa-tools { display: flex; gap: 8px; margin-bottom: 8px; }
    .sa-tools button { border-radius: 8px; border: 1px solid #62579a; background: #32408d; color: #eef2ff; padding: 8px 10px; cursor: pointer; }
    .btn-danger { background: #8b3158 !important; border-color: #b14f7a !important; }
    .btn-warn { background: #7b4f2a !important; border-color: #b38344 !important; }
    .btn-busy { background: #6d5b2b !important; border-color: #b89c52 !important; }
    .btn-ok { background: #2f7a55 !important; border-color: #4bc987 !important; }
    .btn-err { background: #7a2f44 !important; border-color: #cf5e80 !important; }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(7, 8, 25, 0.72);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 60;
    }
    .modal {
      width: min(500px, 92vw);
      border: 1px solid #5a4a93;
      border-radius: 12px;
      background: linear-gradient(180deg, #2a255f, #1f1b49);
      padding: 14px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45);
    }
    .modal h3 { margin: 0 0 8px; font-size: 18px; color: #e9e5ff; }
    .modal p { margin: 0 0 10px; color: #c8c2ea; font-size: 13px; }
    .modal .row { display: grid; grid-template-columns: 1fr; gap: 8px; }
    .modal .row input {
      border-radius: 8px;
      border: 1px solid #6557a6;
      background: rgba(20, 18, 45, 0.85);
      color: #f3f0ff;
      padding: 9px 10px;
    }
    .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
    .table-wrap { overflow: auto; max-height: 420px; border: 1px solid rgba(104, 112, 175, 0.2); border-radius: 8px; }
    .ops-toolbar {
      display: grid;
      grid-template-columns: auto auto 1fr;
      gap: 8px;
      margin-bottom: 10px;
      align-items: center;
    }
    .ops-note { font-size: 12px; color: var(--muted); }
    @media (max-width: 1160px) {
      .grid-top { grid-template-columns: repeat(2, 1fr); }
      .grid-bottom { grid-template-columns: 1fr; }
      .head { grid-template-columns: 1fr; }
      .big { font-size: 44px; }
      .metric { font-size: 42px; }
      .superadmin-grid { grid-template-columns: 1fr; }
      .sa-actions { grid-template-columns: 1fr; }
      .sa-kv { grid-template-columns: 1fr; }
      .ops-toolbar { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="title-row">
      <h1 style="margin:0; font-size:30px; color:#cfd8ff;">Aurora Control Dashboard</h1>
      <button id="logout">Logout</button>
    </div>
    <div id="login-banner" class="login-banner">Authentication required. Redirecting to login...</div>
    <section class="head">
      <input disabled value="Session authentication active (dashboard login)." />
      <button id="refresh">Refresh Now</button>
      <div></div>
    </section>

    <section class="tabs">
      <button class="tab-btn active" data-tab="home">Home</button>
      <button class="tab-btn" data-tab="operations">Operations</button>
      <button id="tab-admin" class="tab-btn superadmin-only" data-tab="admin" style="display:none;">Admin</button>
      <button id="tab-backup" class="tab-btn superadmin-only" data-tab="backup" style="display:none;">Backup</button>
    </section>

    <section id="panel-home" class="tab-panel active">
      <section class="grid-top">
        <article class="card">
          <h2 class="title">Live tasks</h2>
          <div id="live-jobs" class="big">0</div>
          <div class="sub">Open</div>
          <div class="status-row"><span id="queued-jobs">0 queued</span><span id="running-jobs">0 running</span></div>
        </article>
        <article class="card">
          <h2 class="title">Average retries</h2>
          <div><span id="avg-attempts" class="metric">0</span><span class="unit">x</span></div>
          <div class="sub">Attempts per task</div>
          <div class="mini">Higher values may mean unstable processing.</div>
        </article>
        <article class="card">
          <h2 class="title">Success rate</h2>
          <div><span id="success-rate" class="metric">0</span><span class="pct">%</span></div>
          <div class="progress-wrap"><div id="success-fill" class="progress-fill" style="width:0%"></div></div>
          <div class="mini">Completed runs compared with non-completed runs.</div>
        </article>
        <article class="card kpi-emph">
          <h2 class="title">Failed tasks</h2>
          <div id="failed-jobs" class="metric">0</div>
          <div class="sub">Needs attention</div>
          <div class="mini">Review and retry failed tasks.</div>
        </article>
        <article class="card">
          <h2 class="title">Task progress</h2>
          <table class="table">
            <thead><tr><th>Task</th><th>Progress</th><th>Attempts</th></tr></thead>
            <tbody id="job-progression"></tbody>
          </table>
        </article>
      </section>
    </section>

    <section id="panel-operations" class="tab-panel">
      <div class="ops-toolbar">
        <button id="debug-enqueue" class="superadmin-only" style="display:none;">Create random task</button>
        <select id="refresh-interval">
          <option value="1000">Auto-refresh 1s</option>
          <option value="2000">Auto-refresh 2s</option>
          <option value="3000" selected>Auto-refresh 3s</option>
        </select>
        <div id="debug-msg" class="ops-note">Live updates are enabled.</div>
      </div>
      <section class="grid-bottom">
        <article class="card panel">
          <h2 class="title">Task status split</h2>
          <div class="line-wrap">
            <div class="line-legend">
              <span><span class="dot" style="background:var(--cyan)"></span>Queued</span>
              <span style="margin-left:10px"><span class="dot" style="background:var(--amber)"></span>Running</span>
              <span style="margin-left:10px"><span class="dot" style="background:var(--green)"></span>Completed</span>
              <span style="margin-left:10px"><span class="dot" style="background:var(--red)"></span>Failed</span>
            </div>
            <canvas id="trend-canvas" width="760" height="280"></canvas>
          </div>
        </article>
        <article class="card panel">
          <h2 class="title">Latest logs</h2>
          <div id="latest-logs" class="log-stream"></div>
        </article>
        <article class="card panel">
          <h2 class="title">Agent status</h2>
          <table class="table">
            <thead><tr><th>Name</th><th>Status</th><th>Usage</th></tr></thead>
            <tbody id="agent-status"></tbody>
          </table>
        </article>
      </section>
    </section>

    <section id="panel-admin" class="tab-panel superadmin-only" style="display:none;">
      <section class="superadmin">
      <h2 class="sa-title">Superadmin Panel</h2>
      <div class="superadmin-grid">
        <div>
          <div class="sa-box">
            <h3 class="title">Create user</h3>
            <div class="sa-form">
              <input id="new-username" placeholder="Username" />
              <input id="new-password" type="password" placeholder="Password" />
              <select id="new-role">
                <option value="operator">operator</option>
                <option value="admin">admin</option>
                <option value="superadmin">superadmin</option>
              </select>
              <button id="create-user">Create User</button>
              <div id="create-user-msg" class="sa-msg"></div>
            </div>
          </div>
        </div>
        <div>
          <div class="sa-box">
            <h3 class="title">Activity history</h3>
            <div class="sa-tools">
              <button id="audit-export">Export CSV</button>
            </div>
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>When</th><th>User</th><th>Action</th><th>Where</th><th>What</th></tr></thead>
                <tbody id="audit-body"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      </section>
    </section>

    <section id="panel-backup" class="tab-panel superadmin-only" style="display:none;">
      <section class="superadmin">
      <h2 class="sa-title">Backup Center</h2>
      <div style="margin-top: 10px;">
        <h3 class="title">Backup tools</h3>
        <div class="sa-kv">
          <div class="sa-pill">Count: <span id="backup-count">0</span></div>
          <div class="sa-pill">Size: <span id="backup-size">0 MB</span></div>
          <div class="sa-pill">Max: <span id="backup-max-size">0 MB</span></div>
          <div class="sa-pill">Maintenance: <span id="backup-maintenance">off</span></div>
        </div>
        <div class="sa-actions">
          <button id="backup-create">Create backup</button>
          <button id="backup-prune" class="btn-warn">Prune</button>
          <button id="backup-refresh">Refresh list</button>
        </div>
        <div class="sa-actions">
          <select id="backup-select"></select>
          <button id="backup-validate">Validate</button>
          <button id="backup-manifest">Download details</button>
        </div>
        <div class="sa-actions">
          <button id="backup-sync">Copy offsite</button>
          <button id="backup-dryrun">Test restore</button>
          <button id="backup-apply" class="btn-danger">Run restore</button>
        </div>
        <div id="backup-msg" class="sa-msg"></div>
        <div class="sa-backup-table">
          <table class="table">
            <thead><tr><th>ID</th><th>Status</th><th>Created At</th><th>Size</th></tr></thead>
            <tbody id="backup-body"></tbody>
          </table>
        </div>
      </div>
    </section>
    </section>
  </div>

  <div id="confirm-modal" class="modal-backdrop" role="dialog" aria-modal="true">
    <div class="modal">
      <h3 id="confirm-title">Confirm Action</h3>
      <p id="confirm-text">Type confirm token to continue.</p>
      <div class="row">
        <input id="confirm-input" placeholder="Type confirmation text" />
      </div>
      <div class="modal-actions">
        <button id="confirm-cancel">Cancel</button>
        <button id="confirm-submit" class="btn-danger">Confirm</button>
      </div>
    </div>
  </div>

  <script>
    function esc(v) { return String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
    function toNum(v, fallback = 0) { const n = Number(v); return Number.isFinite(n) ? n : fallback; }
    let activeTab = "home";
    let autoRefreshTimer = null;

    function formatDateTime(value) {
      if (!value) return "-";
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return String(value);
      return d.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    function setMsg(id, type, text) {
      const el = document.getElementById(id);
      if (!el) return;
      el.classList.remove("ok", "err", "busy");
      if (type) el.classList.add(type);
      el.textContent = text || "";
    }

    function setOpsMsg(text, kind = "normal") {
      const el = document.getElementById("debug-msg");
      if (!el) return;
      el.style.color = kind === "err" ? "#ff9aa8" : kind === "ok" ? "#8af6b6" : "";
      el.textContent = text;
    }

    function setButtonState(button, state, labelWhenBusy = "Working...") {
      if (!button) return;
      button.classList.remove("btn-busy", "btn-ok", "btn-err");
      if (!button.dataset.originalLabel) button.dataset.originalLabel = button.textContent;
      if (state === "busy") {
        button.disabled = true;
        button.classList.add("btn-busy");
        button.textContent = labelWhenBusy;
        return;
      }
      if (state === "ok") {
        button.disabled = false;
        button.classList.add("btn-ok");
        button.textContent = "Done";
        setTimeout(() => {
          button.classList.remove("btn-ok");
          button.textContent = button.dataset.originalLabel;
        }, 900);
        return;
      }
      if (state === "err") {
        button.disabled = false;
        button.classList.add("btn-err");
        button.textContent = "Failed";
        setTimeout(() => {
          button.classList.remove("btn-err");
          button.textContent = button.dataset.originalLabel;
        }, 1200);
        return;
      }
      button.disabled = false;
      button.textContent = button.dataset.originalLabel;
    }

    function setTab(tabName) {
      activeTab = tabName;
      document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === tabName);
      });
      document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.remove("active"));
      const target = document.getElementById(`panel-${tabName}`);
      if (target) target.classList.add("active");
    }

    function startAutoRefresh() {
      if (autoRefreshTimer) clearInterval(autoRefreshTimer);
      const ms = Number(document.getElementById("refresh-interval")?.value || 3000);
      autoRefreshTimer = setInterval(load, Number.isFinite(ms) ? ms : 3000);
    }

    function openConfirmModal({ title, text, expected, confirmLabel = "Confirm" }) {
      return new Promise((resolve) => {
        const modal = document.getElementById("confirm-modal");
        const titleEl = document.getElementById("confirm-title");
        const textEl = document.getElementById("confirm-text");
        const input = document.getElementById("confirm-input");
        const submit = document.getElementById("confirm-submit");
        const cancel = document.getElementById("confirm-cancel");

        titleEl.textContent = title;
        textEl.textContent = text;
        submit.textContent = confirmLabel;
        input.value = "";
        modal.style.display = "flex";
        input.focus();

        const close = (ok) => {
          modal.style.display = "none";
          submit.removeEventListener("click", onSubmit);
          cancel.removeEventListener("click", onCancel);
          resolve(ok);
        };
        const onCancel = () => close(false);
        const onSubmit = () => {
          const ok = input.value.trim() === expected;
          if (!ok) {
            input.style.borderColor = "#bf5f86";
            return;
          }
          close(true);
        };
        cancel.addEventListener("click", onCancel);
        submit.addEventListener("click", onSubmit);
      });
    }

    function drawStatusDonut(metrics) {
      const canvas = document.getElementById("trend-canvas");
      const ctx = canvas.getContext("2d");
      const w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      const centerX = w / 2;
      const centerY = h / 2 + 8;
      const radius = Math.min(w, h) * 0.32;
      const inner = radius * 0.58;
      const parts = [
        { label: "queued", value: toNum(metrics.queued_jobs), color: "#48cbff" },
        { label: "running", value: toNum(metrics.running_jobs), color: "#e2c84e" },
        { label: "completed", value: toNum(metrics.completed_jobs), color: "#64db66" },
        { label: "failed", value: toNum(metrics.failed_jobs), color: "#ff6f7f" },
      ];
      const total = Math.max(1, parts.reduce((a, p) => a + p.value, 0));
      let start = -Math.PI / 2;
      for (const part of parts) {
        const angle = (part.value / total) * Math.PI * 2;
        const end = start + angle;
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.arc(centerX, centerY, radius, start, end);
        ctx.closePath();
        ctx.fillStyle = part.color;
        ctx.fill();
        start = end;
      }

      ctx.beginPath();
      ctx.arc(centerX, centerY, inner, 0, Math.PI * 2);
      ctx.fillStyle = "#1a1d4d";
      ctx.fill();

      ctx.fillStyle = "#eaf0ff";
      ctx.textAlign = "center";
      ctx.font = "700 30px Segoe UI";
      ctx.fillText(String(total), centerX, centerY - 2);
      ctx.font = "13px Segoe UI";
      ctx.fillStyle = "#b9c2e2";
      ctx.fillText("tasks", centerX, centerY + 18);
    }

    async function ensureAuth() {
      const res = await fetch("/dashboard/auth/status", { credentials: "include" });
      if (!res.ok) return false;
      const data = await res.json();
      if (data.authenticated) return data;
      const banner = document.getElementById("login-banner");
      banner.style.display = "block";
      setTimeout(() => { window.location.href = "/login"; }, 600);
      return null;
    }

    function render(data) {
      const jobs = data.jobs || [];
      const agents = data.agents || [];
      const executions = data.executions || [];
      const metrics = data.metrics || {};

      const liveJobs = toNum(metrics.queued_jobs) + toNum(metrics.running_jobs);
      document.getElementById("live-jobs").textContent = liveJobs;
      document.getElementById("queued-jobs").textContent = `${toNum(metrics.queued_jobs)} queued`;
      document.getElementById("running-jobs").textContent = `${toNum(metrics.running_jobs)} running`;
      document.getElementById("failed-jobs").textContent = toNum(metrics.failed_jobs);

      const avgAttempts = jobs.length ? (jobs.reduce((a, j) => a + toNum(j.attempt_count), 0) / jobs.length) : 0;
      document.getElementById("avg-attempts").textContent = avgAttempts.toFixed(1);

      const completedExec = executions.filter(e => e.status === "completed").length;
      const successRate = executions.length ? Math.round((completedExec / executions.length) * 100) : 0;
      document.getElementById("success-rate").textContent = successRate;
      document.getElementById("success-fill").style.width = `${successRate}%`;

      const progression = data.job_progression || [];
      document.getElementById("job-progression").innerHTML = progression.length
        ? progression.map(row => `<tr>
            <td class="mono">${esc(row.job_id)}</td>
            <td>${esc(row.progress_pct)}%</td>
            <td>${esc(row.attempts)}</td>
          </tr>`).join("")
        : '<tr><td colspan="3" class="mini">No progression data yet.</td></tr>';

      const logs = data.latest_logs || [];
      document.getElementById("latest-logs").innerHTML = logs.length
        ? logs.map(line => `<div class="log-line">[${esc(line.status)}] ${esc(line.job_id)}: ${esc(line.line)}</div>`).join("")
        : '<div class="no-data">No execution logs yet.</div>';

      document.getElementById("agent-status").innerHTML = agents.length
        ? agents.map(a => `<tr>
            <td>${esc(a.name || a.agent_id)}</td>
            <td class="status-${esc(String(a.status).toLowerCase())}">${esc(a.status)}</td>
            <td>CPU ${esc(toNum(a.cpu_load_pct, 0))}% | RAM ${esc(toNum(a.ram_load_pct, 0))}%</td>
          </tr>`).join("")
        : '<tr><td colspan="3" class="mini">No agents registered.</td></tr>';

      drawStatusDonut(metrics);
    }

    function renderAudit(logs) {
      const tbody = document.getElementById("audit-body");
      tbody.innerHTML = (logs || []).map(log => `<tr>
        <td class="mini">${esc(formatDateTime(log.at))}</td>
        <td>${esc(log.actor_username || "-")}</td>
        <td>${esc(log.action)}</td>
        <td class="mini">${esc(log.ip_address || "-")}</td>
        <td class="mono">${esc((log.resource_type || "") + ":" + (log.resource_id || ""))}</td>
      </tr>`).join("") || '<tr><td colspan="5" class="mini">No logs yet.</td></tr>';
    }

    function bytesToText(bytes) {
      const n = toNum(bytes);
      if (n <= 0) return "0 MB";
      return `${(n / (1024 * 1024)).toFixed(2)} MB`;
    }

    function renderBackups(backups, policy, summary) {
      const rows = backups || [];
      const tbody = document.getElementById("backup-body");
      tbody.innerHTML = rows.length
        ? rows.map(row => `<tr>
            <td class="mono">${esc(row.backup_id)}</td>
            <td>${esc(row.status)}</td>
            <td class="mini">${esc(formatDateTime(row.created_at))}</td>
            <td>${bytesToText(row.size_bytes)}</td>
          </tr>`).join("")
        : '<tr><td colspan="4" class="mini">No backups yet.</td></tr>';

      const select = document.getElementById("backup-select");
      const options = rows.map(row => `<option value="${esc(row.backup_id)}">${esc(row.backup_id)} (${esc(row.status)})</option>`).join("");
      select.innerHTML = options || '<option value="">No backup</option>';

      document.getElementById("backup-count").textContent = String(toNum(summary?.count));
      document.getElementById("backup-size").textContent = bytesToText(summary?.total_size_bytes);
      document.getElementById("backup-max-size").textContent = bytesToText(summary?.max_storage_bytes);
      document.getElementById("backup-maintenance").textContent = policy?.maintenance_mode?.enabled ? "on" : "off";
    }

    async function runBackupAction(action, method = "POST", body = null, button = null, taskLabel = "Task") {
      setMsg("backup-msg", "busy", `${taskLabel}...`);
      setButtonState(button, "busy");
      const opts = { method, credentials: "include", headers: {} };
      if (body) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
      const res = await fetch(action, opts);
      if (!res.ok) {
        let reason = "request failed";
        try {
          const err = await res.json();
          reason = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail || err);
        } catch (_) {}
        setMsg("backup-msg", "err", `${taskLabel}: failed`);
        setButtonState(button, "err");
        return null;
      }
      const data = await res.json();
      setMsg("backup-msg", "ok", `${taskLabel}: success`);
      setButtonState(button, "ok");
      return data;
    }

    async function loadBackupPanel(summaryOverride = null) {
      const [backupsRes, policyRes] = await Promise.all([
        fetch("/superadmin/backups?limit=30", { credentials: "include" }),
        fetch("/superadmin/backups/policy", { credentials: "include" }),
      ]);
      if (!backupsRes.ok || !policyRes.ok) return;
      const backups = await backupsRes.json();
      const policy = await policyRes.json();
      const summary = summaryOverride || {};
      renderBackups(backups.backups || [], policy, summary);
    }

    async function load() {
      const auth = await ensureAuth();
      if (!auth) return;
      const isSuperadmin = !!auth.is_superadmin;
      document.querySelectorAll(".superadmin-only").forEach(el => {
        el.style.display = isSuperadmin ? "" : "none";
      });
      if (!isSuperadmin && (activeTab === "admin" || activeTab === "backup")) {
        setTab("home");
      }
      const res = await fetch("/dashboard/api/overview", { credentials: "include" });
      if (!res.ok) return;
      const overview = await res.json();
      render(overview);
      if (isSuperadmin) {
        const logRes = await fetch("/superadmin/audit/logs?limit=30", { credentials: "include" });
        if (logRes.ok) {
          const logData = await logRes.json();
          renderAudit(logData.logs || []);
        }
        await loadBackupPanel(overview.backup_summary || {});
      }
    }

    document.getElementById("refresh").addEventListener("click", load);
    document.getElementById("refresh-interval").addEventListener("change", () => {
      startAutoRefresh();
      setOpsMsg("Refresh interval updated.", "ok");
    });
    document.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", () => setTab(btn.dataset.tab));
    });
    document.getElementById("logout").addEventListener("click", async () => {
      await fetch("/dashboard/logout", { method: "POST", credentials: "include" });
      window.location.href = "/login";
    });
    document.getElementById("create-user").addEventListener("click", async () => {
      const btn = document.getElementById("create-user");
      const username = document.getElementById("new-username").value.trim();
      const password = document.getElementById("new-password").value;
      const role = document.getElementById("new-role").value;
      setMsg("create-user-msg", "busy", "Creating user...");
      setButtonState(btn, "busy", "Creating...");
      const res = await fetch("/superadmin/users", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, role }),
      });
      if (!res.ok) {
        setMsg("create-user-msg", "err", "Failed to create user.");
        setButtonState(btn, "err");
        return;
      }
      setMsg("create-user-msg", "ok", "User created.");
      setButtonState(btn, "ok");
      document.getElementById("new-password").value = "";
      load();
    });
    document.getElementById("audit-export").addEventListener("click", () => {
      window.location.href = "/superadmin/audit/logs/export?limit=5000";
    });
    document.getElementById("debug-enqueue").addEventListener("click", async () => {
      const btn = document.getElementById("debug-enqueue");
      setButtonState(btn, "busy", "Creating...");
      const res = await fetch("/superadmin/debug/enqueue-random", { method: "POST", credentials: "include" });
      if (!res.ok) {
        setButtonState(btn, "err");
        setOpsMsg("Create random task: failed", "err");
        return;
      }
      const data = await res.json();
      setButtonState(btn, "ok");
      setOpsMsg(`Random task created: ${data.job_id} (${data.mode})`, "ok");
      await load();
    });
    document.getElementById("backup-refresh").addEventListener("click", loadBackupPanel);
    document.getElementById("backup-create").addEventListener("click", async () => {
      const btn = document.getElementById("backup-create");
      await runBackupAction("/superadmin/backups/create", "POST", null, btn, "Create backup");
      await loadBackupPanel();
      await load();
    });
    document.getElementById("backup-validate").addEventListener("click", async () => {
      const id = document.getElementById("backup-select").value;
      if (!id) return;
      const btn = document.getElementById("backup-validate");
      await runBackupAction(`/superadmin/backups/${id}/validate`, "POST", null, btn, "Validate backup");
      await loadBackupPanel();
    });
    document.getElementById("backup-manifest").addEventListener("click", () => {
      const id = document.getElementById("backup-select").value;
      if (!id) return;
      window.location.href = `/superadmin/backups/${id}/manifest/download`;
    });
    document.getElementById("backup-sync").addEventListener("click", async () => {
      const id = document.getElementById("backup-select").value;
      if (!id) return;
      const btn = document.getElementById("backup-sync");
      await runBackupAction(`/superadmin/backups/${id}/offsite-sync`, "POST", null, btn, "Copy offsite");
      await loadBackupPanel();
    });
    document.getElementById("backup-dryrun").addEventListener("click", async () => {
      const id = document.getElementById("backup-select").value;
      if (!id) return;
      const btn = document.getElementById("backup-dryrun");
      await runBackupAction(`/superadmin/backups/${id}/restore?dry_run=true`, "POST", null, btn, "Test restore");
      await loadBackupPanel();
    });
    document.getElementById("backup-apply").addEventListener("click", async () => {
      const id = document.getElementById("backup-select").value;
      if (!id) return;
      const ok = await openConfirmModal({
        title: "Confirm Restore Apply",
        text: `This will run restore apply. Type backup id ${id} to continue.`,
        expected: id,
        confirmLabel: "Apply Restore",
      });
      if (!ok) {
        setMsg("backup-msg", "err", "Cancelled: confirmation mismatch.");
        return;
      }
      const btn = document.getElementById("backup-apply");
      await runBackupAction(`/superadmin/backups/${id}/restore?dry_run=false`, "POST", { confirm: id }, btn, "Run restore");
      await loadBackupPanel();
      await load();
    });
    document.getElementById("backup-prune").addEventListener("click", async () => {
      const token = "PRUNE";
      const ok = await openConfirmModal({
        title: "Confirm Prune",
        text: `Prune will delete old backups by policy. Type ${token} to continue.`,
        expected: token,
        confirmLabel: "Run Prune",
      });
      if (!ok) {
        setMsg("backup-msg", "err", "Cancelled: prune confirmation mismatch.");
        return;
      }
      const btn = document.getElementById("backup-prune");
      await runBackupAction("/superadmin/backups/prune", "POST", null, btn, "Prune backups");
      await loadBackupPanel();
      await load();
    });
    setTab("home");
    load();
    startAutoRefresh();
  </script>
</body>
</html>
"""
