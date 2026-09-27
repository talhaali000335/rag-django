from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from django.conf import settings
from mlops.metrics import HALLUCINATION_SCORE_HISTOGRAM

llm = ChatGroq(
    model=settings.LLM_MODEL,
    temperature=0.0,
    api_key=settings.GROQ_API_KEY,
)

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
        result = llm.invoke(HALLUCINATION_PROMPT.format(
            context=context,
            generation=generation,
        ))
        score = float(result.content.strip())
        score = max(0.0, min(1.0, score))   # clamp between 0 and 1
    except Exception:
        score = 0.0   # if LLM returns unexpected format, assume no hallucination

    HALLUCINATION_SCORE_HISTOGRAM.observe(score)
    return {'hallucination_score': score}