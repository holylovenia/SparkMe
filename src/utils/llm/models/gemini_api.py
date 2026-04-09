import os
from src.utils.llm.models.data import ModelResponse

GEMINI_API_MODEL = "gemini-2.5-flash"

class GeminiAPIEngine:
    """
    Engine wrapper for Gemini models via Google's Generative AI API (api key based).

    Environment variables:
        GEMINI_API_KEY:   Google Generative AI API key (required)
        GEMINI_API_MODEL: Model name (default: gemini-2.5-flash)
    """

    def __init__(self, model_name: str = None, **kwargs):
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "The 'google-generativeai' package is required. "
                "Install it with: pip install google-generativeai"
            )

        api_key = kwargs.pop("api_key", None) or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY must be set in .env or passed as api_key kwarg."
            )

        self.model_name = model_name or os.getenv("GEMINI_API_MODEL", GEMINI_API_MODEL)
        self.temperature = kwargs.pop("temperature", 0.0)
        self.max_tokens  = kwargs.pop("max_tokens", None) or kwargs.pop("max_output_tokens", 8192)

        genai.configure(api_key=api_key)

        self._genai = genai

    def invoke(self, prompt, **kwargs) -> ModelResponse:
        generation_config = self._genai.types.GenerationConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
        )

        model = self._genai.GenerativeModel(model_name=self.model_name)
        response = model.generate_content(
            prompt,
            generation_config=generation_config,
        )

        model_response = ModelResponse(response.text)

        if hasattr(response, 'usage_metadata'):
            usage = response.usage_metadata
            model_response.response_metadata = {
                'token_usage': {
                    'prompt_tokens':     getattr(usage, 'prompt_token_count',     0),
                    'completion_tokens': getattr(usage, 'candidates_token_count', 0),
                    'total_tokens':      getattr(usage, 'total_token_count',      0),
                }
            }

        return model_response