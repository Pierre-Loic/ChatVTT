"use strict";

/* Écran public (vidéoprojecteur) : affichage seul, aucune commande. */

function big(text, cls) { return el("div", { class: "d-big " + (cls || ""), text }); }

function render(app, state) {
  app.dataset.screen = state.state;
  app.innerHTML = "";
  const head = el("header", { class: "d-head" }, [
    state.total_rounds ? el("span", { text: `Manche ${state.round_number} / ${state.total_rounds}` }) : null,
  ]);
  app.appendChild(head);
  if (state.teams && state.teams.length) app.appendChild(scoreboard(state));

  const s = state.state;
  if (s === "CONFIGURATION") {
    app.appendChild(big("Vélo & IA Générative"));
    app.appendChild(el("p", { class: "d-sub", text: "Configuration en cours…" }));
  } else if (s === "BIKE_CHECK") {
    const bc = state.bike_check || {};
    app.appendChild(big("Vérification du vélo"));
    app.appendChild(big(`${bc.revolutions || 0}`, "d-count"));
    app.appendChild(el("p", { class: "d-sub", text: bc.passed ? "✅ Vélo validé" : `Seuil : ${bc.threshold} tours` }));
  } else if (s === "INTRODUCTION") {
    app.appendChild(big("L'énergie de l'IA générative"));
    app.appendChild(el("p", { class: "d-sub", text: "Deux facteurs : le modèle choisi et la longueur de la sortie." }));
    app.appendChild(el("p", { class: "callout", text: "Estimations pédagogiques (Ecologits), pas une mesure réelle." }));
  } else if (s === "SPINNING") {
    app.appendChild(big("Tirage du scénario"));
    app.appendChild(wheels(state.scenario, true));
  } else if (s === "TEAM_SELECTION") {
    const ts = state.team_selection || {};
    app.appendChild(big(`${teamName(state, state.current_team_id)} choisit son coureur`));
    app.appendChild(big(fmtSeconds(ts.seconds_remaining || 0), "d-count"));
  } else if (s === "PREPARATION") {
    const p = state.preparation || {};
    app.appendChild(big("PRÉPAREZ-VOUS"));
    app.appendChild(big(`${Math.max(0, Math.ceil(p.seconds_remaining || 0))}`, "d-count huge"));
  } else if (s === "CYCLING") {
    const c = state.cycling || {};
    app.appendChild(big("PÉDALEZ !", "d-pedal"));
    app.appendChild(big(fmtSeconds(c.seconds_remaining || 0), "d-count"));
    app.appendChild(el("div", { class: "d-metrics" }, [
      el("div", {}, [el("span", { text: "Tours" }), el("b", { text: String(c.revolutions || 0) })]),
      el("div", {}, [el("span", { text: "Progression" }), el("b", { text: `${c.performance_percent || 0} %` })]),
    ]));
    app.appendChild(gauge(c.performance_percent || 0));
    if (state.scenario) app.appendChild(el("p", { class: "d-sub", text: `${state.scenario.model_name} — ${state.scenario.output_description}` }));
    if (c.signal_lost) app.appendChild(el("p", { class: "warn", text: "⚠️ Signal vélo perdu — le chrono continue." }));
  } else if (s === "RESULT") {
    const r = state.result || {};
    app.appendChild(big(`Palier ${r.tier_reached || 0} %`, "tier-" + (r.tier_reached || 0)));
    app.appendChild(big(`${r.performance_percent} %`, "d-count"));
    app.appendChild(el("p", { class: "d-sub", text: `${r.score} points — ${r.scenario ? r.scenario.model_name : ""}` }));
  } else if (s === "FINAL_RESULTS") {
    const f = state.final_results || {};
    const w = f.winner_team_id ? teamName(state, f.winner_team_id) : (f.is_draw ? "Égalité" : "");
    app.appendChild(big(w === "Égalité" ? "Égalité" : `🏆 ${w}`));
    app.appendChild(el("p", { class: "d-sub", text: `${f.total_revolutions} tours — ${f.total_target_energy_mwh} mWh d'IA estimés` }));
  } else if (s === "PEDAGOGICAL_SUMMARY") {
    const su = state.pedagogical_summary || {};
    app.appendChild(big("Synthèse"));
    app.appendChild(el("p", { class: "d-sub", html: `Partie : <b>${su.actual_total_energy_mwh} mWh</b> — modèle léger : <b>${su.counterfactual_lightest_total_mwh} mWh</b>` }));
    app.appendChild(el("p", { class: "hint", text: su.disclaimer || "" }));
  }
}

startPolling(render, 800);
