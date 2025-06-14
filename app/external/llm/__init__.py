from ..constants import GROQ_API_KEY
from .base_llm import BaseLLM
from .groq_llm import GroqLLM


async def get_groq_llm() -> BaseLLM:
    return GroqLLM(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        api_key=GROQ_API_KEY,
    )
