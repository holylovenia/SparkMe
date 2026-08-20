import os
from langchain_openai import ChatOpenAI
from src.utils.llm.models.data import ModelResponse

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY  = "<X>"
OPENROUTER_MODEL    = "cohere/command-a"

# Provider quantization preference, from best to worst.
# Each tier is passed to OpenRouter as provider.quantizations; a tier of None
# means "no filter" (OpenRouter's default routing across all providers).
# See https://openrouter.ai/docs/guides/routing/provider-selection#quantization
QUANTIZATION_TIERS = (
    ["fp32", "fp16", "bf16"],   # 32-bit / 16-bit
    ["fp8", "mxfp8", "int8"],   # 8-bit
    None,                       # anything
)

# Substrings OpenRouter uses when no provider matches the routing filters.
_NO_PROVIDER_HINTS = (
    "no allowed providers",
    "no endpoints found",
    "no providers",
)

# ChatOpenAI accepts `extra_body` directly in newer langchain-openai versions;
# older ones require it to go through `model_kwargs`. Passing it through
# model_kwargs when the field exists raises a ValueError, so detect it once.
_CHAT_OPENAI_FIELDS = getattr(ChatOpenAI, "model_fields", None) \
    or getattr(ChatOpenAI, "__fields__", {})
_SUPPORTS_EXTRA_BODY = "extra_body" in _CHAT_OPENAI_FIELDS


def _is_no_provider_error(exc) -> bool:
    """True if the request failed because no provider matched the filters."""
    if getattr(exc, "status_code", None) == 404 or \
            getattr(getattr(exc, "response", None), "status_code", None) == 404:
        return True

    message = str(exc).lower()
    return any(hint in message for hint in _NO_PROVIDER_HINTS)


class OpenRouterEngine:
    """
    Engine wrapper for OpenRouter.

    Requests are restricted to 16-bit / 32-bit providers. If no such provider
    is available for the model, the request is retried against 8-bit providers,
    and finally against any provider.

    Environment variables (optional overrides):
        OPENROUTER_BASE_URL: API base URL
        OPENROUTER_API_KEY:  Bearer token
        OPENROUTER_MODEL:    Model name
    """

    def __init__(self, **kwargs):
        base_url   = kwargs.pop("base_url",   None) or os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL)
        api_key    = kwargs.pop("api_key",    None) or os.getenv("OPENROUTER_API_KEY",  OPENROUTER_API_KEY)
        model_name = kwargs.pop("model_name", None) or os.getenv("OPENROUTER_MODEL",    OPENROUTER_MODEL)

        self.model_name = model_name
        self.base_url   = base_url
        self.api_key    = api_key
        self.kwargs     = kwargs

        # Lowest tier index known to work for this model; starts at the most
        # preferred tier and only moves down after a tier is found unavailable.
        self.quantization_tier = 0

        self.clients = {}
        self.client = self._get_client(0)

    def _get_client(self, tier: int) -> ChatOpenAI:
        """Build (and cache) a client pinned to the given quantization tier."""
        if tier not in self.clients:
            self.clients[tier] = self._build_client(QUANTIZATION_TIERS[tier])

        return self.clients[tier]

    def _build_client(self, quantizations) -> ChatOpenAI:
        kwargs = dict(self.kwargs)

        if quantizations:
            if _SUPPORTS_EXTRA_BODY:
                extra_body = dict(kwargs.get("extra_body") or {})
            else:
                model_kwargs = dict(kwargs.get("model_kwargs") or {})
                extra_body   = dict(model_kwargs.get("extra_body") or {})

            provider = dict(extra_body.get("provider") or {})
            provider["quantizations"] = list(quantizations)
            extra_body["provider"] = provider

            if _SUPPORTS_EXTRA_BODY:
                kwargs["extra_body"] = extra_body
            else:
                model_kwargs["extra_body"] = extra_body
                kwargs["model_kwargs"] = model_kwargs

        return ChatOpenAI(
            model_name=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            **kwargs
        )

    def invoke(self, prompt, **kwargs) -> ModelResponse:
        last_tier = len(QUANTIZATION_TIERS) - 1

        for tier in range(self.quantization_tier, last_tier + 1):
            client = self._get_client(tier)

            try:
                response = client.invoke(prompt, **kwargs)
            except Exception as e:
                # Only widen the filter when the model genuinely has no
                # provider at this quantization; other errors are real.
                if tier == last_tier or not _is_no_provider_error(e):
                    raise
                continue

            # Remember the tier that worked so later turns skip the probing.
            self.quantization_tier = tier
            self.client = client

            model_response = ModelResponse(response.content)

            if hasattr(response, 'response_metadata') and \
                    'token_usage' in response.response_metadata:
                model_response.response_metadata = {
                    'token_usage': response.response_metadata['token_usage']
                }

            return model_response