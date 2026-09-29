from langchain_groq import ChatGroq
from django.conf import settings


def build_llm(temperature: float = 0.0):
    """Primary model first; on any error, fall back to the next models in order."""
    llms = [
        ChatGroq(
            model=name,
            temperature=temperature,
            api_key=settings.GROQ_API_KEY,
            max_retries=1,   # fail fast so the fallback kicks in quickly
            timeout=30,
        )
        for name in settings.LLM_MODELS
    ]
    return llms[0].with_fallbacks(llms[1:]) if len(llms) > 1 else llms[0]