import os
from langchain_openai import ChatOpenAI
from src.utils.llm.models.data import ModelResponse

COHERE_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY  = "<X>"
COHERE_OPENROUTER_MODEL    = "cohere/command-r7b-12-2024"

class CohereOpenRouterEngine:
    """
    Engine wrapper for Cohere Command R7B served via OpenRouter.

    Environment variables (optional overrides):
        COHERE_OPENROUTER_BASE_URL: API base URL
        OPENROUTER_API_KEY:  Bearer token
        COHERE_OPENROUTER_MODEL:    Model name
    """

    def __init__(self, **kwargs):
        base_url   = kwargs.pop("base_url",   None) or os.getenv("COHERE_OPENROUTER_BASE_URL", COHERE_OPENROUTER_BASE_URL)
        api_key    = kwargs.pop("api_key",    None) or os.getenv("OPENROUTER_API_KEY",  OPENROUTER_API_KEY)
        model_name = kwargs.pop("model_name", None) or os.getenv("COHERE_OPENROUTER_MODEL",    COHERE_OPENROUTER_MODEL)

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