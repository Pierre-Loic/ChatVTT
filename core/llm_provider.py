"""LLMProvider — génération réelle vs simulée (§9 SPEC.md).

Le jeu ne dépend JAMAIS d'un LLM réel pour fonctionner (§10, §11). Le provider
simulé est le défaut ; toute erreur d'un provider réel est capturée et
n'interrompt pas le déroulement du jeu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GenerationRequest:
    provider: str
    model_name: str
    output_description: str  # affiché aux joueurs (§9)
    output_tokens: int
    prompt_template: str | None  # texte réellement envoyé au LLM (§9)


@dataclass(frozen=True)
class GenerationResult:
    text: str
    simulated: bool
    error: str | None = None


class LLMProvider(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationResult: ...


class SimulatedLLMProvider:
    """Provider par défaut : aucun appel réseau (§9, §10)."""

    def generate(self, request: GenerationRequest) -> GenerationResult:
        placeholder = (
            f"[Génération simulée — {request.model_name}]\n"
            f"Tâche : {request.output_description}\n"
            f"Longueur cible : ~{request.output_tokens} tokens.\n\n"
            "Ce texte est un contenu factice. Aucune requête n'a été envoyée à "
            "un modèle. L'énergie affichée est une estimation pédagogique "
            "(source Ecologits), pas une mesure réelle."
        )
        return GenerationResult(text=placeholder, simulated=True)


class AnthropicLLMProvider:
    """Provider réel optionnel (§9, §12). Nécessite ``pip install anthropic``
    et la clé ``ANTHROPIC_API_KEY``. Toute erreur est renvoyée dans
    ``GenerationResult.error`` sans lever d'exception (§11)."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001", api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key

    def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            import anthropic  # import paresseux : dépendance optionnelle
        except ImportError:
            return GenerationResult(
                text="", simulated=True,
                error="Package 'anthropic' non installé — génération simulée.",
            )
        try:
            client = anthropic.Anthropic(api_key=self._api_key) if self._api_key else anthropic.Anthropic()
            prompt = request.prompt_template or request.output_description
            message = client.messages.create(
                model=self._model,
                max_tokens=max(16, request.output_tokens),
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                block.text for block in message.content if getattr(block, "type", None) == "text"
            )
            return GenerationResult(text=text, simulated=False)
        except Exception as exc:  # noqa: BLE001 — on ne bloque jamais le jeu (§11)
            return GenerationResult(text="", simulated=True, error=str(exc))
