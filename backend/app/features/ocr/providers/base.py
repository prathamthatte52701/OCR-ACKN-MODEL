from abc import ABC, abstractmethod


class AIProvider(ABC):
    """Provider-abstraction so Groq (default) can be swapped for OpenAI/
    Claude/Gemini later via config, without touching extraction.py or the
    pipeline that calls this."""

    @abstractmethod
    async def extract(self, system_prompt: str, user_prompt: str) -> str:
        """Returns the raw text response (expected to contain JSON)."""
        raise NotImplementedError
