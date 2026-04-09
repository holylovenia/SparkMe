import os
from langchain_openai import ChatOpenAI
from src.utils.llm.models.data import ModelResponse

GPT4O_MINI_PROXY_BASE_URL = "https://api.openai-next.com/v1"
GPT4O_MINI_PROXY_API_KEY  = "sk-hrgTnQZuOPTIlaRFEaF4185412C54958Ad6943547f4e4727"
GPT4O_MINI_PROXY_MODEL    = "gpt-4o-mini"

class GPT4OMiniProxyEngine:
    """
    Engine wrapper for gpt-4o-mini served via an OpenAI-compatible proxy.

    Environment variables (optional overrides):
        GPT4O_MINI_PROXY_BASE_URL: API base URL
        GPT4O_MINI_PROXY_API_KEY:  Bearer token
        GPT4O_MINI_PROXY_MODEL:    Model name
    """

    def __init__(self, **kwargs):
        base_url   = kwargs.pop("base_url",   None) or os.getenv("GPT4O_MINI_PROXY_BASE_URL", GPT4O_MINI_PROXY_BASE_URL)
        api_key    = kwargs.pop("api_key",    None) or os.getenv("GPT4O_MINI_PROXY_API_KEY",  GPT4O_MINI_PROXY_API_KEY)
        model_name = kwargs.pop("model_name", None) or os.getenv("GPT4O_MINI_PROXY_MODEL",    GPT4O_MINI_PROXY_MODEL)

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