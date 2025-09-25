# Philippe Limantour - March 2024
"""Model pricing utilities.

Contains backward compatible legacy pricing dictionary plus richer metadata for
new Azure OpenAI / reasoning models. Placeholder (0) pricing MUST be updated
with authoritative Sweden Central EUR rates when confirmed.
"""
try:  # fallback if termcolor missing in some minimal contexts
  from termcolor import colored  # type: ignore
except Exception:  # pragma: no cover
  def colored(x, *_, **__):  # noqa: D401
    return x
"""
Model pricing and metadata.

This module originally exposed `model_pricing_euros` with a very small schema
{ model: { Context, NbTokens, Input, Output } } used by get_completion_pricing_from_usage.

To support newer Azure OpenAI / reasoning models (gpt-4.1 family, gpt-5, o*-series) and
future dynamic adaptation, we introduce an extended metadata structure `MODEL_METADATA`.

For now we keep backward compatibility:
 - Existing callers continue to use model_pricing_euros (legacy structure)
 - New models are added to both structures (with placeholder pricing = 0 when
   authoritative region-specific EUR pricing not yet confirmed).

NOTE: Pricing entries with 0 and `"estimate": False` MUST be updated once verified.
Sweden Central region pricing should be fetched manually from the Azure pricing page.
"""

# Legacy structure (backward compatibility). New models inserted with zero pricing placeholders.
model_pricing_euros = {
    "gpt-3.5-turbo-0125": {"Context": 16000, "NbTokens": 1000, "Input": 0.0005, "Output": 0.0014},
    "gpt-3.5-turbo-instruct": {"Context": 4000, "NbTokens": 1000, "Input": 0.0014, "Output": 0.002},
    "gpt-4-turbo": {"Context": 128000, "NbTokens": 1000, "Input": 0.010, "Output": 0.028},
    "gpt-4-turbo-vision": {"Context": 128000, "NbTokens": 1000, "Input": 0.010, "Output": 0.028},
    "gpt-4": {"Context": 8000, "NbTokens": 1000, "Input": 0.028, "Output": 0.056},
    "gpt-4o": {"Context": 128000, "NbTokens": 1000, "Input": 0.0047, "Output": 0.0139},
    "gpt-4o-mini": {"Context": 128000, "NbTokens": 1000, "Input": 0.00014277, "Output": 0.0005711},
    "o3-mini": {"Context": 200000, "NbTokens": 1000, "Input": 0.0010470, "Output": 0.004187884},
    "o1-mini": {"Context": 128000, "NbTokens": 1000, "Input": 0.0010470, "Output": 0.004187884},
    "gpt-4-32k": {"Context": 32000, "NbTokens": 1000, "Input": 0.056, "Output": 0.112},
    "azureai": {"Context": 32000, "NbTokens": 1000, "Input": 0.0074088, "Output": 0.0222264},  # Mistral Large

    # --- Newer model families (PLACEHOLDER pricing: set to 0 until confirmed) ---
    # GPT-4.1 series
    # Converted from user-provided Global pricing (per 1M -> per 1K division by 1000)
    # GPT-4.1: Input €1.73/1M => 0.00173/1K, Output €6.91/1M => 0.00691/1K (cached input tracked only in metadata)
    "gpt-4.1": {"Context": 128000, "NbTokens": 1000, "Input": 0.00173, "Output": 0.00691},
    # GPT-4.1-mini: Input 0.35/1M => 0.00035/1K, Output 1.39/1M => 0.00139/1K
    "gpt-4.1-mini": {"Context": 128000, "NbTokens": 1000, "Input": 0.00035, "Output": 0.00139},
    # GPT-4.1-nano: Input 0.09/1M => 0.00009/1K, Output 0.35/1M => 0.00035/1K
    "gpt-4.1-nano": {"Context": 128000, "NbTokens": 1000, "Input": 0.00009, "Output": 0.00035},
    # GPT-5 (reasoning) - pricing likely different structure; we still map Input/Output for continuity
    # GPT-5 pricing updated (Global) original figures were per 1M tokens:
    #   Input: €1.08 /1M, Cached Input: €0.11 /1M, Output: €8.63 /1M
    # Converted to per 1K tokens (divide by 1000):
    #   Input: 0.00108, Cached Input: 0.00011, Output: 0.00863
    # NOTE: Legacy structure lacks cached input field; only Input & Output used.
    "gpt-5": {"Context": 400000, "NbTokens": 1000, "Input": 0.00108, "Output": 0.00863},
    # GPT-5-mini Global pricing: Input 0.22/1M => 0.00022/1K, Output 1.73/1M => 0.00173/1K
    "gpt-5-mini": {"Context": 400000, "NbTokens": 1000, "Input": 0.00022, "Output": 0.00173},
    # o3 / o4 lines (some already partially represented)
    # o4-mini Global pricing: Input 0.95/1M => 0.00095/1K, Output 3.80/1M => 0.00380/1K
    "o4-mini": {"Context": 128000, "NbTokens": 1000, "Input": 0.00095, "Output": 0.00380},
}

# Extended metadata for richer logic (reasoning flags, modalities, etc.).
# Keys mirror deployment model names used in code.
MODEL_METADATA = {
    # Example existing entries (subset). Input/output costs reference model_pricing_euros.
    "gpt-4o": {
        "family": "gpt-4o",
        "reasoning": False,
        "modalities": ["text", "vision"],
        "context_window": {"input": 128000, "output": 16384},
        "currency": "EUR",
        "input_cost_per_1k": model_pricing_euros["gpt-4o"]["Input"],
        "output_cost_per_1k": model_pricing_euros["gpt-4o"]["Output"],
        "estimate": False,
        "updated_at": "2025-09-23"
    },
    "gpt-4o-mini": {
        "family": "gpt-4o-mini",
        "reasoning": False,
        "modalities": ["text"],
        "context_window": {"input": 128000, "output": 16384},
        "currency": "EUR",
        "input_cost_per_1k": model_pricing_euros["gpt-4o-mini"]["Input"],
        "output_cost_per_1k": model_pricing_euros["gpt-4o-mini"]["Output"],
        "estimate": False,
        "updated_at": "2025-09-23"
    },
    # New GPT-4.1 series (placeholder)
    "gpt-4.1": {
        "family": "gpt-4.1",
        "reasoning": False,
        "modalities": ["text", "vision"],
        "context_window": {"input": 128000, "output": 16384},
        "currency": "EUR",
        "input_cost_per_1k": 0.00173,
        "cached_input_cost_per_1k": 0.00044,  # 0.44 /1M => 0.00044 /1K
        "output_cost_per_1k": 0.00691,
        "estimate": False,
        "updated_at": "2025-09-23",
        "source": "Converted from user-provided Global pricing (per 1M)"
    },
    "gpt-4.1-mini": {
        "family": "gpt-4.1-mini",
        "reasoning": False,
        "modalities": ["text"],
        "context_window": {"input": 128000, "output": 16384},
        "currency": "EUR",
        "input_cost_per_1k": 0.00035,
        "cached_input_cost_per_1k": 0.00009,
        "output_cost_per_1k": 0.00139,
        "estimate": False,
        "updated_at": "2025-09-23",
        "source": "Converted from user-provided Global pricing (per 1M)"
    },
    "gpt-4.1-nano": {
        "family": "gpt-4.1-nano",
        "reasoning": False,
        "modalities": ["text"],
        "context_window": {"input": 128000, "output": 32768},
        "currency": "EUR",
        "input_cost_per_1k": 0.00009,
        "cached_input_cost_per_1k": 0.00003,
        "output_cost_per_1k": 0.00035,
        "estimate": False,
        "updated_at": "2025-09-23",
        "source": "Converted from user-provided Global pricing (per 1M)"
    },
    # GPT-5 reasoning (placeholder pricing)
    "gpt-5": {
        "family": "gpt-5",
        "reasoning": True,
        "modalities": ["text", "vision"],
        "context_window": {"input": 272000, "output": 128000},
        "currency": "EUR",
        "input_cost_per_1k": 0.00108,
        "cached_input_cost_per_1k": 0.00011,  # per 1K tokens after conversion
        "output_cost_per_1k": 0.00863,
        "estimate": False,
        "updated_at": "2025-09-23",
        "source": "Converted from user-provided GPT-5 Global pricing (original per 1M) 2025-08-07"
    },
    "gpt-5-mini": {
        "family": "gpt-5-mini",
        "reasoning": True,
        "modalities": ["text", "vision"],
        "context_window": {"input": 272000, "output": 128000},
        "currency": "EUR",
        "input_cost_per_1k": 0.00022,
        "cached_input_cost_per_1k": 0.00003,
        "output_cost_per_1k": 0.00173,
        "estimate": False,
        "updated_at": "2025-09-23",
        "source": "Converted from user-provided Global pricing (per 1M)"
    },
    # o4-mini reasoning-lite style placeholder
    "o4-mini": {
        "family": "o4-mini",
        "reasoning": True,
        "modalities": ["text", "vision"],
        "context_window": {"input": 128000, "output": 16384},
        "currency": "EUR",
        "input_cost_per_1k": 0.00095,
        "output_cost_per_1k": 0.00380,
        "estimate": False,
        "updated_at": "2025-09-23",
        "source": "Converted from user-provided Global pricing (per 1M)"
    }
}

# Function to calculate the cost of a completion based on the number of tokens used in the prompt
def get_completion_pricing_from_usage(model, nb_tokens_input_prompt, nb_tokens_output_prompt):
    model = model.lower()
    if model in model_pricing_euros.keys():
        model_cost = model_pricing_euros[model]
        model_cost_nbtokens = model_cost["NbTokens"]
        model_cost_input_pricing = model_cost["Input"]
        model_cost_output_pricing = model_cost["Output"]

        input_cost = (nb_tokens_input_prompt / model_cost_nbtokens) * model_cost_input_pricing
        output_cost = (nb_tokens_output_prompt / model_cost_nbtokens) * model_cost_output_pricing

        print(colored(f"Input Tokens: {nb_tokens_input_prompt} - Output Tokens: {nb_tokens_output_prompt}", "green"))

        return input_cost, output_cost
    else:
        print(colored(f"Model {model} not found in the pricing list", "red"))
        return 0, 0


def get_model_metadata(model_name: str):
    """Return extended metadata for a model if available."""
    return MODEL_METADATA.get(model_name, None)


def is_reasoning_model(model_name: str) -> bool:
    """Heuristic reasoning model detector with metadata preference."""
    meta = get_model_metadata(model_name)
    if meta:
        return meta.get("reasoning", False)
    lowered = model_name.lower()
    return any(lowered.startswith(pfx) for pfx in ("gpt-5", "o1", "o3", "o4"))