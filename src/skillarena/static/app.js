const Merit = {
  api: "http://127.0.0.1:8000",

  player: () => localStorage.getItem("merit_player") || null,
  tier: () => localStorage.getItem("merit_tier") || "Bronze",
  setPlayer(n) { localStorage.setItem("merit_player", n); },
  setTier(t) { localStorage.setItem("merit_tier", t); },
  logout() { localStorage.removeItem("merit_player"); localStorage.removeItem("merit_tier"); location.href = "/"; },

  requireAuth() {
    if (!Merit.player()) { location.href = "/login"; return false; }
    return true;
  },

  tierBadge(t) { return `<span class="badge tier-${t}">${t}</span>`; },
  diffClass(d) { return `diff-${d}`; },

  fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  },

  renderNav(active) {
    const p = Merit.player();
    const t = Merit.tier();
    return `
      <nav class="nav">
        <div class="nav-inner">
          <a href="/home" class="nav-brand">
            <span class="nav-brand-mark">M</span>
            <span>Merit</span>
          </a>
          <div class="nav-links">
            <a href="/home" class="nav-link ${active === "home" ? "active" : ""}">Solve</a>
            <a href="/leaderboard" class="nav-link ${active === "leaderboard" ? "active" : ""}">Leaderboard</a>
          </div>
          <div class="nav-right">
            ${p ? `
              <a href="/u/${encodeURIComponent(p)}" class="nav-user">
                ${Merit.tierBadge(t)}
                <span>${p}</span>
              </a>
              <button class="nav-logout" onclick="Merit.logout()">Logout</button>
            ` : `<a href="/login" class="btn btn-primary">Sign in</a>`}
          </div>
        </div>
      </nav>
    `;
  },

  mountNav(active) {
    const el = document.getElementById("nav");
    if (el) el.innerHTML = Merit.renderNav(active);
  },
};