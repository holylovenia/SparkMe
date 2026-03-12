
import os
from lorem_text import lorem

from src.utils.llm.models.data import ModelResponse

class LipsumEngine:
    """
    A wrapper class for Lorem Ipsum random generator.
    """
    def __init__(self, model_name: str, **kwargs):
        
        self.model_name = model_name
        self.kwargs = kwargs
    
    def invoke(self, prompt, **kwargs) -> ModelResponse:
        """
        Invoke the random generation.

        Args:
            prompt: The input prompt as a string
            **kwargs: Additional keyword arguments for the model invocation

        Returns:
            A ModelResponse object with the model's response and token usage
        """
        # Generate content
        text = self.model_name + " " + lorem.sentence()

        # Create ModelResponse with content and usage metadata
        model_response = ModelResponse(text)

        return model_response 