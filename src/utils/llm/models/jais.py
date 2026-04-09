import os
from langchain_openai import ChatOpenAI
from src.utils.llm.models.data import ModelResponse

JAIS2_BASE_URL = "http://108.136.150.20:8000/v1"
JAIS2_API_KEY  = "mbzuai-jais2"
JAIS2_MODEL    = "Jais-2-70B-Chat"

class JaisEngine:
    """
    Engine wrapper for the JAIS 2 model served via an OpenAI-compatible API.

    Environment variables (optional overrides):
        JAIS2_BASE_URL: API base URL  (default: http://108.136.150.20:8000/v1)
        JAIS2_API_KEY:  Bearer token  (default: mbzuai-jais2)
        JAIS2_MODEL:    Model name    (default: Jais-2-70B-Chat)
    """

    def __init__(self, **kwargs):
        base_url  = kwargs.pop("base_url",  None) or os.getenv("JAIS2_BASE_URL", JAIS2_BASE_URL)
        api_key   = kwargs.pop("api_key",   None) or os.getenv("JAIS2_API_KEY",  JAIS2_API_KEY)
        model_name = kwargs.pop("model_name", None) or os.getenv("JAIS2_MODEL",  JAIS2_MODEL)

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