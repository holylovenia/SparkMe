import os
from langchain_openai import ChatOpenAI
from src.utils.llm.models.data import ModelResponse

FANAR_BASE_URL = "https://api.fanar.qa/v1"
FANAR_MODEL    = "Fanar-S-1-7B"

class FanarEngine:
    """
    Engine wrapper for Fanar models via the Fanar API.

    Environment variables:
        FANAR_API_KEY:   Bearer token (required)
        FANAR_BASE_URL:  API base URL (default: https://api.fanar.qa/v1)
        FANAR_MODEL:     Model name   (default: Fanar-S-1-7B)

    Available chat models:
        Fanar, Fanar-S-1-7B, Fanar-C-1-8.7B, Fanar-C-2-27B,
        Fanar-Sadiq, Fanar-Guard-2, Fanar-Diwan
    """

    def __init__(self, model_name: str = None, **kwargs):
        api_key = kwargs.pop("api_key", None) or os.getenv("FANAR_API_KEY")
        if not api_key:
            raise ValueError(
                "FANAR_API_KEY must be set in .env or passed as api_key kwarg."
            )

        base_url   = kwargs.pop("base_url",   None) or os.getenv("FANAR_BASE_URL", FANAR_BASE_URL)
        model_name = model_name or os.getenv("FANAR_MODEL", FANAR_MODEL)

        self.model_name = model_name

        self.client = ChatOpenAI(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            **kwargs
        )

    def invoke(self, prompt, **kwargs) -> ModelResponse:
        response = self.client.invoke(prompt, **kwargs)

        model_response = ModelResponse(response.content)

        if hasattr(response, 'response_metadata') and \
                'token_usage' in response.response_metadata:
            model_response.response_metadata = {
                'token_usage': response.response_metadata['token_usage']
            }

        return model_response