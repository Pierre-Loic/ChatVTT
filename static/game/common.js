"use strict";

/* Helpers partagés entre l'écran animateur et l'écran public. */

async function apiGet(url) {
  const r = await fetch(url, { headers: { "Accept": "application/json" } });
  return r.json();
}

async function apiPost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": window.CSRF_TOKEN || "",
    },
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await r.json(); } catch (_) { /* noop */ }
  if (!r.ok) {
    const msg = data.error || `Erreur ${r.status}`;
    flash(msg);
    return { ok: false, error: msg, data };
  }
  return { ok: true, data };
}

const action = (name) => apiPost(`/api/action/${name}`);
const pedal = (count) => apiPost("/api/pedal", { count });
const selectRunner = (playerId) => apiPost("/api/select-runner", { player_id: playerId });

function flash(message) {
  let el = document.getElementById("flash");
  if (!el) {
    el = document.createElement("div");
    el.id = "flash";
    el.className = "flash";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 4000);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function teamName(state, teamId) {
  const t = (state.teams || []).find((x) => x.id === teamId);
  return t ? t.name : "—";
}
function playerName(state, playerId) {
  const p = (state.players || []).find((x) => x.id === playerId);
  return p ? p.name : "—";
}

function gauge(percent) {
  const clamped = Math.max(0, Math.min(120, percent));
  const wrap = el("div", { class: "gauge" });
  const fill = el("div", { class: "gauge-fill" });
  fill.style.width = `${Math.min(100, clamped)}%`;
  if (percent >= 100) fill.classList.add("full");
  wrap.appendChild(fill);
  for (const tier of [25, 50, 75, 100]) {
    wrap.appendChild(el("span", { class: "gauge-tick", style: `left:${tier}%` }));
  }
  return wrap;
}

/* Roues type machine à sous : on ne fait qu'illustrer le scénario déjà tiré
   côté serveur (§6.4). */
function wheels(scenario, spinning) {
  const box = el("div", { class: "wheels" });
  const w1 = el("div", { class: "wheel" + (spinning ? " spin" : "") }, [
    el("span", { class: "wheel-label", text: "Modèle" }),
    el("strong", { text: scenario ? scenario.model_name : "…" }),
  ]);
  const w2 = el("div", { class: "wheel" + (spinning ? " spin" : "") }, [
    el("span", { class: "wheel-label", text: "Sortie" }),
    el("strong", { text: scenario ? scenario.output_description : "…" }),
  ]);
  box.append(w1, w2);
  return box;
}

function scenarioCard(scenario) {
  if (!scenario) return el("p", { text: "Aucun scénario." });
  return el("div", { class: "scenario-card" }, [
    el("div", { class: "kv" }, [el("span", { text: "Fournisseur" }), el("b", { text: scenario.provider })]),
    el("div", { class: "kv" }, [el("span", { text: "Modèle" }), el("b", { text: scenario.model_name })]),
    el("div", { class: "kv" }, [el("span", { text: "Sortie" }), el("b", { text: scenario.output_description })]),
    el("div", { class: "kv" }, [el("span", { text: "Tokens" }), el("b", { text: String(scenario.output_tokens) })]),
    el("div", { class: "kv" }, [el("span", { text: "Énergie IA estimée" }), el("b", { text: `${scenario.energy_mwh} mWh` })]),
    el("div", { class: "kv" }, [el("span", { text: "Source" }), el("b", { text: scenario.source || "Ecologits" })]),
  ]);
}

function scoreboard(state) {
  return el("div", { class: "scoreboard" },
    (state.teams || []).map((t) =>
      el("div", { class: "team-score" + (t.id === state.current_team_id ? " active" : "") }, [
        el("span", { class: "team-score-name", text: t.name }),
        el("span", { class: "team-score-value", text: String(t.score) }),
      ])
    )
  );
}

function startPolling(render, intervalMs = 700) {
  const app = document.getElementById("app");
  let busy = false;
  async function tick() {
    if (busy) return;
    busy = true;
    try {
      const state = await apiGet("/api/state");
      const d = document.getElementById("disclaimer");
      if (d && state.disclaimer) d.textContent = state.disclaimer;
      render(app, state);
    } catch (e) {
      console.error(e);
    } finally {
      busy = false;
    }
  }
  tick();
  setInterval(tick, intervalMs);
}

function fmtSeconds(s) {
  return `${Math.max(0, Math.ceil(s))} s`;
}
