"""Current Codex model choices and forward aliases for existing bindings."""

SOL = "gpt-6.2-sol"
ASTRA = "gpt-6.2-astra"
MODEL_EFFORTS = {
    "gpt-6-luna": ("low", "medium", "high", "xhigh", "max"),
    "gpt-6.1-terra": ("low", "medium", "high", "xhigh", "max", "ultra"),
    SOL: ("low", "medium", "high", "xhigh", "max", "ultra"),
    ASTRA: ("low", "medium", "high", "xhigh", "max", "ultra"),
}
LEGACY_MODELS = {
    "gpt-6-sol": SOL,
    "gpt-6.1-sol": SOL,
    "gpt-6-astra": ASTRA,
    "gpt-6.1-astra": ASTRA,
}
MODEL_CHOICES = "GPT-6 Luna, GPT-6.1 Terra, GPT-6.2 Sol or GPT-6.2 Astra"


def current_model(model: str) -> str:
    """Resolve a saved model ID when launching new work; leave stored history intact."""
    return LEGACY_MODELS.get(model, model)
