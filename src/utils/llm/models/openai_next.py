import os
from langchain_openai import ChatOpenAI
from src.utils.llm.models.data import ModelResponse

OPENAI_NEXT_BASE_URL = "https://api.openai-next.com/v1"
OPENAI_NEXT_API_KEY  = "sk-hrgTnQZuOPTIlaRFEaF4185412C54958Ad6943547f4e4727"
OPENAI_NEXT_MODEL    = "gpt-4o-mini"

class OpenAINextEngine:
    """
    Engine wrapper for OpenAI Next.

    Environment variables (optional overrides):
        OPENAI_NEXT_BASE_URL: API base URL
        OPENAI_NEXT_API_KEY:  Bearer token
        OPENAI_NEXT_MODEL:    Model name
    """

    def __init__(self, **kwargs):
        base_url   = kwargs.pop("base_url",   None) or os.getenv("OPENAI_NEXT_BASE_URL", OPENAI_NEXT_BASE_URL)
        api_key    = kwargs.pop("api_key",    None) or os.getenv("OPENAI_NEXT_API_KEY",  OPENAI_NEXT_API_KEY)
        model_name = kwargs.pop("model_name", None) or os.getenv("OPENAI_NEXT_MODEL",    OPENAI_NEXT_MODEL)

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