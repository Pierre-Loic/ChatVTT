"use strict";

/* Écran animateur : pilote la machine à états (§5, §6). */

const CFG = window.GAME_CONFIG;
const SIMULATED = CFG.bikeSensor !== "gpio";

function header(state) {
  const wrap = el("header", { class: "board-header" });
  const left = el("div", { class: "board-header-left" });
  if (state.total_rounds > 0) {
    left.appendChild(el("span", { class: "round-badge",
      text: `Manche ${state.round_number} / ${state.total_rounds}` }));
  }
  left.appendChild(el("span", { class: "state-badge", text: state.state }));
  wrap.append(left, el("div", { id: "hdr-scores" }), el("button", {
    class: "btn btn-ghost btn-reset",
    text: "Reset",
    onclick: async () => {
      if (confirm("Réinitialiser toute la partie ? (retour à la configuration)")) {
        await action("reset");
      }
    },
  }));
  return wrap;
}

function updateHeader(state) {
  const slot = document.getElementById("hdr-scores");
  if (!slot) return;
  slot.innerHTML = "";
  if (state.teams && state.teams.length) slot.appendChild(scoreboard(state));
}

function pedalButtons() {
  if (!SIMULATED) return el("p", { class: "hint", text: "Capteur GPIO : pédalez sur le vélo." });
  return el("div", { class: "pedal-buttons" },
    [1, 10, 100].map((n) =>
      el("button", { class: "btn btn-pedal", text: `+${n}`, onclick: () => pedal(n) })
    )
  );
}

/* ---------- CONFIGURATION (§6.1) ---------- */
function renderConfig(state) {
  const form = el("form", { class: "card config-form" });
  const size = el("input", { type: "number", min: "1", max: "12", value: "3", name: "n", id: "cfg-n" });
  const nameA = el("input", { type: "text", value: "Équipe A", id: "cfg-a" });
  const nameB = el("input", { type: "text", value: "Équipe B", id: "cfg-b" });
  const playersA = el("textarea", { id: "cfg-pa", rows: "5", placeholder: "Un nom par ligne" });
  const playersB = el("textarea", { id: "cfg-pb", rows: "5", placeholder: "Un nom par ligne" });

  form.append(
    el("h1", { text: "Configuration de la partie" }),
    el("label", { text: "Participants par équipe (identique des deux côtés)" }), size,
    el("p", { class: "hint", id: "cfg-rounds", text: "Nombre total de manches : 6" }),
    el("div", { class: "two-col" }, [
      el("div", {}, [el("label", { text: "Nom équipe A" }), nameA,
        el("label", { text: "Joueurs équipe A" }), playersA]),
      el("div", {}, [el("label", { text: "Nom équipe B" }), nameB,
        el("label", { text: "Joueurs équipe B" }), playersB]),
    ]),
    el("button", { class: "btn btn-primary", type: "submit", text: "Valider et démarrer la vérification du vélo" }),
  );

  size.addEventListener("input", () => {
    const n = parseInt(size.value, 10) || 0;
    document.getElementById("cfg-rounds").textContent = `Nombre total de manches : ${2 * n}`;
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const n = parseInt(size.value, 10) || 0;
    const linesA = playersA.value.split("\n").map((s) => s.trim()).filter(Boolean);
    const linesB = playersB.value.split("\n").map((s) => s.trim()).filter(Boolean);
    const res = await apiPost("/api/configure", {
      players_per_team: n,
      team_a_name: nameA.value, team_b_name: nameB.value,
      players_a: linesA, players_b: linesB,
    });
    if (res.ok) await action("begin_bike_check");
  });

  return form;
}

/* ---------- BIKE_CHECK (§6.2) ---------- */
function renderBikeCheck(state) {
  const card = el("div", { class: "card center" }, [
    el("h1", { text: "Vérification du vélo" }),
    el("p", { text: "Pédalez quelques secondes pour valider le capteur." }),
    el("div", { class: "big-number", id: "bc-rev", text: "0" }),
    el("p", { class: "hint", id: "bc-status" }),
    el("p", { class: "hint", id: "bc-cadence" }),
    pedalButtons(),
    el("button", { class: "btn btn-primary", id: "bc-continue", disabled: "disabled",
      text: "Continuer", onclick: () => action("confirm_bike_check") }),
  ]);
  return card;
}
function patchBikeCheck(state) {
  const bc = state.bike_check || {};
  setText("bc-rev", `${bc.revolutions || 0}`);
  setText("bc-status", bc.passed
    ? "✅ Vélo validé"
    : `Seuil : ${bc.threshold} tours (encore ${Math.max(0, bc.threshold - (bc.revolutions || 0))})`);
  setText("bc-cadence", `Cadence : ${bc.cadence_rpm || 0} tr/min`);
  const btn = document.getElementById("bc-continue");
  if (btn) btn.disabled = !bc.passed;
}

/* ---------- INTRODUCTION (§6.3) ---------- */
function renderIntro(state) {
  const i = state.introduction || {};
  return el("div", { class: "card" }, [
    el("h1", { text: "Comment l'IA générative consomme de l'énergie" }),
    el("p", { text: i.note || "" }),
    el("div", { class: "two-col" }, [
      el("div", {}, [el("h3", { text: "Modèles en jeu" }),
        el("ul", {}, (i.models || []).map((m) => el("li", { text: m })))]),
      el("div", {}, [el("h3", { text: "Types de sortie" }),
        el("ul", {}, (i.outputs || []).map((o) => el("li", { text: o })))]),
    ]),
    el("p", { class: "hint", text: `Longueurs de sortie : de ${(i.token_range || [0, 0])[0]} à ${(i.token_range || [0, 0])[1]} tokens.` }),
    el("p", { class: "callout", text: "⚠️ Les valeurs affichées sont des ESTIMATIONS pédagogiques (Ecologits), pas une mesure réelle de datacenter." }),
    el("button", { class: "btn btn-primary", text: "Lancer le tirage", onclick: () => action("start_game") }),
  ]);
}

/* ---------- SPINNING (§6.4) ---------- */
function renderSpinning(state) {
  return el("div", { class: "card center" }, [
    el("h1", { text: "Tirage du scénario" }),
    wheels(state.scenario, true),
    scenarioCard(state.scenario),
    el("p", { class: "hint", text: "Le couple modèle / sortie est tiré parmi les scénarios réellement présents en base." }),
    el("button", { class: "btn btn-primary", text: "Valider ce scénario", onclick: () => action("confirm_spin") }),
  ]);
}

/* ---------- TEAM_SELECTION (§6.5) ---------- */
function renderTeamSelection(state) {
  const card = el("div", { class: "card" }, [
    el("h1", { html: `Équipe <b>${teamName(state, state.current_team_id)}</b> : choisissez votre coureur` }),
    el("div", { class: "countdown", id: "ts-count", text: "30" }),
    el("div", { class: "runner-grid", id: "ts-grid" }),
    el("p", { class: "hint", id: "ts-note" }),
    el("button", { class: "btn btn-primary", id: "ts-continue", disabled: "disabled",
      text: "Lancer la préparation", onclick: () => action("confirm_runner") }),
  ]);
  return card;
}
function patchTeamSelection(state) {
  const ts = state.team_selection || {};
  setText("ts-count", fmtSeconds(ts.seconds_remaining || 0));
  const grid = document.getElementById("ts-grid");
  if (grid && grid.dataset.n !== String((ts.eligible || []).length) + (ts.selected_player_id || "")) {
    grid.dataset.n = String((ts.eligible || []).length) + (ts.selected_player_id || "");
    grid.innerHTML = "";
    for (const p of ts.eligible || []) {
      grid.appendChild(el("button", {
        class: "btn btn-runner" + (p.id === ts.selected_player_id ? " selected" : ""),
        text: p.name, onclick: () => selectRunner(p.id),
      }));
    }
  }
  setText("ts-note", ts.needs_host
    ? "⏱️ Temps écoulé — l'animateur doit désigner un coureur."
    : (ts.selected_player_id ? `Coureur : ${playerName(state, ts.selected_player_id)}` : ""));
  const btn = document.getElementById("ts-continue");
  if (btn) btn.disabled = !ts.selected_player_id;
}

/* ---------- PREPARATION (§6.6) ---------- */
function renderPreparation(state) {
  return el("div", { class: "card center prep" }, [
    el("h1", { text: "Préparez-vous" }),
    el("div", { class: "countdown big", id: "prep-count", text: "10" }),
    el("p", { html: `<b>${playerName(state, state.current_player_id)}</b> — ${teamName(state, state.current_team_id)}` }),
  ]);
}
function patchPreparation(state) {
  const p = state.preparation || {};
  setText("prep-count", `${Math.max(0, Math.ceil(p.seconds_remaining || 0))}`);
}

/* ---------- CYCLING (§6.7) ---------- */
function renderCycling(state) {
  return el("div", { class: "card cycling" }, [
    el("div", { class: "cycling-top" }, [
      el("div", {}, [el("span", { class: "hint", text: "Équipe" }),
        el("h2", { text: teamName(state, state.current_team_id) })]),
      el("div", { class: "chrono", id: "cy-time", text: "60" }),
      el("div", {}, [el("span", { class: "hint", text: "Coureur" }),
        el("h2", { text: playerName(state, state.current_player_id) })]),
    ]),
    scenarioCard(state.scenario),
    el("div", { class: "cycling-metrics" }, [
      metric("Tours", "cy-rev"), metric("Énergie produite (J)", "cy-j"),
      metric("Objectif (J)", "cy-target"), metric("Progression", "cy-pct"),
    ]),
    el("div", { id: "cy-gauge" }),
    el("p", { class: "warn hidden", id: "cy-signal", text: "⚠️ Signal vélo perdu — le chrono continue." }),
    pedalButtons(),
    el("p", { class: "callout", text: "Le chrono reste fixé à 60 s : atteindre 100 % ne termine pas la manche en avance." }),
  ]);
}
function patchCycling(state) {
  const c = state.cycling || {};
  setText("cy-time", fmtSeconds(c.seconds_remaining || 0));
  setText("cy-rev", `${c.revolutions || 0}`);
  setText("cy-j", `${c.human_energy_joules || 0}`);
  setText("cy-target", `${c.target_energy_joules || 0}`);
  setText("cy-pct", `${c.performance_percent || 0} %`);
  const g = document.getElementById("cy-gauge");
  if (g) { g.innerHTML = ""; g.appendChild(gauge(c.performance_percent || 0)); }
  const sig = document.getElementById("cy-signal");
  if (sig) sig.classList.toggle("hidden", !c.signal_lost);
}

/* ---------- RESULT (§6.8) ---------- */
function renderResult(state) {
  const r = state.result || {};
  const isLast = state.round_number >= state.total_rounds;
  return el("div", { class: "card center" }, [
    el("h1", { text: `Résultat — manche ${r.round_number}` }),
    el("div", { class: "tier-badge tier-" + (r.tier_reached || 0), text: `Palier ${r.tier_reached || 0} %` }),
    el("p", { class: "big-number", text: `${r.performance_percent} %` }),
    el("div", { class: "result-grid" }, [
      kv("Tours", r.revolutions), kv("Énergie produite", `${r.human_energy_joules} J`),
      kv("Objectif IA", `${r.target_energy_mwh} mWh (${r.target_energy_joules} J)`),
      kv("Points gagnés", r.score),
    ]),
    scenarioCard(r.scenario),
    r.generation && r.generation.text
      ? el("details", { class: "gen" }, [el("summary", { text: r.generation.simulated ? "Texte généré (simulé)" : "Texte généré" }),
          el("pre", { text: r.generation.text })])
      : null,
    r.generation && r.generation.error
      ? el("p", { class: "warn", text: `LLM : ${r.generation.error} (le jeu continue)` }) : null,
    el("button", { class: "btn btn-primary",
      text: isLast ? "Voir les résultats finaux" : "Manche suivante",
      onclick: () => action("next_round") }),
  ]);
}

/* ---------- FINAL_RESULTS (§6.10) ---------- */
function renderFinal(state) {
  const f = state.final_results || {};
  const winner = f.winner_team_id ? teamName(state, f.winner_team_id) : (f.is_draw ? "Égalité" : "—");
  return el("div", { class: "card" }, [
    el("h1", { text: "Résultats finaux" }),
    el("p", { class: "big-number", text: winner === "Égalité" ? "Égalité" : `🏆 ${winner}` }),
    scoreboard(state),
    el("div", { class: "result-grid" }, [
      kv("Tours cumulés", f.total_revolutions),
      kv("Énergie cycliste totale", `${f.total_human_energy_joules} J`),
      kv("Énergie IA estimée cumulée", `${f.total_target_energy_mwh} mWh`),
    ]),
    el("h3", { text: "Scénarios tirés" }),
    el("table", { class: "table" }, [
      el("tr", {}, [el("th", { text: "Modèle" }), el("th", { text: "Sortie" }), el("th", { text: "Fois" }), el("th", { text: "mWh cumulés" })]),
      ...(f.scenario_breakdown || []).map((s) => el("tr", {}, [
        el("td", { text: s.model_name }), el("td", { text: s.output_description }),
        el("td", { text: String(s.count) }), el("td", { text: String(s.total_energy_mwh) }),
      ])),
    ]),
    el("button", { class: "btn btn-primary", text: "Synthèse pédagogique", onclick: () => action("to_summary") }),
  ]);
}

/* ---------- PEDAGOGICAL_SUMMARY (§6.11) ---------- */
function renderSummary(state) {
  const s = state.pedagogical_summary || {};
  return el("div", { class: "card" }, [
    el("h1", { text: "Synthèse pédagogique" }),
    el("p", { text: "L'énergie d'une génération dépend de deux facteurs visibles pendant le jeu : le modèle choisi et la quantité de sortie produite." }),
    el("table", { class: "table" }, [
      el("tr", {}, [el("th", { text: "#" }), el("th", { text: "Modèle" }), el("th", { text: "Sortie" }),
        el("th", { text: "Tokens" }), el("th", { text: "mWh" }), el("th", { text: "Perf." })]),
      ...(s.rounds || []).map((r) => el("tr", {}, [
        el("td", { text: String(r.round_number) }), el("td", { text: r.model_name }),
        el("td", { text: r.output_description }), el("td", { text: String(r.output_tokens) }),
        el("td", { text: String(r.energy_mwh) }), el("td", { text: `${r.performance_percent} %` }),
      ])),
    ]),
    el("div", { class: "callout" }, [
      el("p", { html: `Énergie IA estimée cumulée de la partie : <b>${s.actual_total_energy_mwh} mWh</b>.` }),
      el("p", { html: `Et si le modèle le plus léger de la base (<b>${s.counterfactual_lightest_model}</b>) avait été utilisé à chaque manche : ~<b>${s.counterfactual_lightest_total_mwh} mWh</b>.` }),
      el("p", { html: `Et si la sortie la plus courte (« ${s.counterfactual_shortest_output} ») avait été demandée à chaque manche : ~<b>${s.counterfactual_shortest_total_mwh} mWh</b>.` }),
    ]),
    el("p", { class: "hint", text: s.disclaimer || "" }),
    el("button", { class: "btn btn-ghost", text: "Nouvelle partie", onclick: () => action("reset") }),
  ]);
}

/* ---------- routeur ---------- */
const SCREENS = {
  CONFIGURATION: { render: renderConfig },
  BIKE_CHECK: { render: renderBikeCheck, patch: patchBikeCheck },
  INTRODUCTION: { render: renderIntro },
  SPINNING: { render: renderSpinning },
  TEAM_SELECTION: { render: renderTeamSelection, patch: patchTeamSelection },
  PREPARATION: { render: renderPreparation, patch: patchPreparation },
  CYCLING: { render: renderCycling, patch: patchCycling },
  RESULT: { render: renderResult },
  NEXT_TEAM: { render: () => el("p", { class: "loading", text: "…" }) },
  FINAL_RESULTS: { render: renderFinal },
  PEDAGOGICAL_SUMMARY: { render: renderSummary },
};

function render(app, state) {
  const scr = SCREENS[state.state] || SCREENS.CONFIGURATION;
  if (app.dataset.screen !== state.state) {
    app.dataset.screen = state.state;
    app.innerHTML = "";
    app.appendChild(header(state));
    app.appendChild(scr.render(state));
    app._patch = scr.patch || null;
  }
  updateHeader(state);
  if (app._patch) app._patch(state);
}

/* helpers locaux */
function setText(id, txt) { const n = document.getElementById(id); if (n) n.textContent = txt; }
function metric(label, id) {
  return el("div", { class: "metric" }, [el("span", { class: "metric-label", text: label }),
    el("span", { class: "metric-value", id })]);
}
function kv(k, v) { return el("div", { class: "kv" }, [el("span", { text: k }), el("b", { text: String(v) })]); }

startPolling(render);
