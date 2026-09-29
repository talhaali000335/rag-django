import re
from langchain_core.prompts import ChatPromptTemplate
from mlops.metrics import HALLUCINATION_SCORE_HISTOGRAM
from .llm import build_llm

_llm = None


def _get_llm():
    """Created on first use, not at import time."""
    global _llm
    if _llm is None:
        _llm = build_llm(temperature=0.0)
    return _llm


HALLUCINATION_PROMPT = ChatPromptTemplate.from_template("""
You are checking if an AI answer is grounded in the provided context.

Context:
{context}

Answer to check:
{generation}

Is the answer fully supported by the context above?
Answer ONLY with a number between 0.0 and 1.0 where:
- 0.0 means completely grounded (no hallucination)
- 1.0 means completely hallucinated (not supported by context at all)
Return ONLY the number, nothing else. Example: 0.2
""")


def _parse_score(text: str) -> float:
    """Pull the first number out of the reply, even if the model adds extra words."""
    match = re.search(r'\d*\.?\d+', text or '')
    if not match:
        return 0.0
    return max(0.0, min(1.0, float(match.group())))


def hallucination_check_node(state: dict) -> dict:
    """Check if the generated answer is grounded in the retrieved documents."""
    context = "\n\n---\n\n".join(
        d['content'] for d in state.get('graded_docs', [])
    )
    generation = state.get('generation', '')

    # If nothing to check, assume it's fine
    if not context or not generation:
        return {'hallucination_score': 0.0}

    try:
        result = _get_llm().invoke(HALLUCINATION_PROMPT.format(
            context=context,
            generation=generation,
        ))
        score = _parse_score(result.content)
    except Exception:
        score = 0.0   # if every model fails, don't block the answer

    HALLUCINATION_SCORE_HISTOGRAM.observe(score)
    return {'hallucination_score': score}