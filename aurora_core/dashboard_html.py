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
      display: none;
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
    .sa-msg { min-height: 16px; font-size: 12px; color: #c4bfff; }
    @media (max-width: 1160px) {
      .grid-top { grid-template-columns: repeat(2, 1fr); }
      .grid-bottom { grid-template-columns: 1fr; }
      .head { grid-template-columns: 1fr; }
      .big { font-size: 44px; }
      .metric { font-size: 42px; }
      .superadmin-grid { grid-template-columns: 1fr; }
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

    <section id="superadmin" class="superadmin">
      <h2 class="sa-title">Superadmin Panel</h2>
      <div class="superadmin-grid">
        <div>
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
        <div>
          <h3 class="title">System logs (audit)</h3>
          <table class="table">
            <thead><tr><th>When</th><th>User</th><th>Action</th><th>Where</th><th>What</th></tr></thead>
            <tbody id="audit-body"></tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="grid-top">
      <article class="card">
        <h2 class="title">Live jobs</h2>
        <div id="live-jobs" class="big">0</div>
        <div class="sub">Open</div>
        <div class="status-row"><span id="queued-jobs">0 queued</span><span id="running-jobs">0 running</span></div>
      </article>
      <article class="card">
        <h2 class="title">Avg. retries</h2>
        <div><span id="avg-attempts" class="metric">0</span><span class="unit">x</span></div>
        <div class="sub">Attempts / job</div>
        <div class="mini">Higher means more unstable workload routing.</div>
      </article>
      <article class="card">
        <h2 class="title">Execution success</h2>
        <div><span id="success-rate" class="metric">0</span><span class="pct">%</span></div>
        <div class="progress-wrap"><div id="success-fill" class="progress-fill" style="width:0%"></div></div>
        <div class="mini">Completed vs non-completed executions.</div>
      </article>
      <article class="card kpi-emph">
        <h2 class="title">Failed jobs</h2>
        <div id="failed-jobs" class="metric">0</div>
        <div class="sub">Need attention</div>
        <div class="mini">Use retry/backoff + checkpoint detail panel.</div>
      </article>
      <article class="card">
        <h2 class="title">Job progression</h2>
        <table class="table">
          <thead><tr><th>Job</th><th>Progress</th><th>Attempts</th></tr></thead>
          <tbody id="job-progression"></tbody>
        </table>
      </article>
    </section>

    <section class="grid-bottom">
      <article class="card panel">
        <h2 class="title">New jobs vs completed</h2>
        <div class="line-wrap">
          <div class="line-legend">
            <span><span class="dot" style="background:var(--cyan)"></span>New</span>
            <span style="margin-left:10px"><span class="dot" style="background:var(--amber)"></span>Completed</span>
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
          <thead><tr><th>Name</th><th>Status</th><th>Load</th></tr></thead>
          <tbody id="agent-status"></tbody>
        </table>
      </article>
    </section>
  </div>

  <script>
    function esc(v) { return String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
    function toNum(v, fallback = 0) { const n = Number(v); return Number.isFinite(n) ? n : fallback; }

    function groupTrend(jobs) {
      const rows = jobs.slice(0, 24).reverse();
      let completedSoFar = 0;
      return rows.map((j, idx) => {
        if (j.status === "completed") completedSoFar += 1;
        return { x: idx + 1, newJobs: idx + 1, completed: completedSoFar };
      });
    }

    function drawTrend(points) {
      const canvas = document.getElementById("trend-canvas");
      const ctx = canvas.getContext("2d");
      const w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      const pad = 30, xw = w - pad * 2, yh = h - pad * 2;
      const maxY = Math.max(1, ...points.map(p => Math.max(p.newJobs, p.completed)));

      ctx.strokeStyle = "rgba(122,130,193,0.25)";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 5; i++) {
        const y = pad + (yh / 5) * i;
        ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - pad, y); ctx.stroke();
      }

      function drawLine(series, color) {
        if (!points.length) return;
        ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.beginPath();
        points.forEach((p, i) => {
          const x = pad + (points.length <= 1 ? 0 : (i / (points.length - 1)) * xw);
          const y = pad + yh - (series(p) / maxY) * yh;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
      drawLine(p => p.newJobs, "#48cbff");
      drawLine(p => p.completed, "#e2c84e");
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
            <td class="mono">${esc(a.agent_id)}</td>
            <td class="status-${esc(String(a.status).toLowerCase())}">${esc(a.status)}</td>
            <td>${esc(a.active_leases)}/${esc(a.max_concurrency)}</td>
          </tr>`).join("")
        : '<tr><td colspan="3" class="mini">No agents registered.</td></tr>';

      drawTrend(groupTrend(jobs));
    }

    function renderAudit(logs) {
      const tbody = document.getElementById("audit-body");
      tbody.innerHTML = (logs || []).map(log => `<tr>
        <td class="mini">${esc(log.at || "-")}</td>
        <td>${esc(log.actor_username || "-")}</td>
        <td>${esc(log.action)}</td>
        <td class="mini">${esc(log.ip_address || "-")}</td>
        <td class="mono">${esc((log.resource_type || "") + ":" + (log.resource_id || ""))}</td>
      </tr>`).join("") || '<tr><td colspan="5" class="mini">No logs yet.</td></tr>';
    }

    async function load() {
      const auth = await ensureAuth();
      if (!auth) return;
      const isSuperadmin = !!auth.is_superadmin;
      document.getElementById("superadmin").style.display = isSuperadmin ? "block" : "none";
      const res = await fetch("/dashboard/api/overview", { credentials: "include" });
      if (!res.ok) return;
      render(await res.json());
      if (isSuperadmin) {
        const logRes = await fetch("/superadmin/audit/logs?limit=30", { credentials: "include" });
        if (logRes.ok) {
          const logData = await logRes.json();
          renderAudit(logData.logs || []);
        }
      }
    }

    document.getElementById("refresh").addEventListener("click", load);
    document.getElementById("logout").addEventListener("click", async () => {
      await fetch("/dashboard/logout", { method: "POST", credentials: "include" });
      window.location.href = "/login";
    });
    document.getElementById("create-user").addEventListener("click", async () => {
      const username = document.getElementById("new-username").value.trim();
      const password = document.getElementById("new-password").value;
      const role = document.getElementById("new-role").value;
      const msg = document.getElementById("create-user-msg");
      msg.textContent = "";
      const res = await fetch("/superadmin/users", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, role }),
      });
      if (!res.ok) {
        msg.textContent = "Failed to create user.";
        return;
      }
      msg.textContent = "User created.";
      document.getElementById("new-password").value = "";
      load();
    });

    load();
    setInterval(load, 2500);
  </script>
</body>
</html>
"""
