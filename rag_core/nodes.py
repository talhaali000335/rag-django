from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from .retriever import retrieve_relevant_chunks
from django.conf import settings
import time
from mlops.metrics import LATENCY_HISTOGRAM, RETRIEVAL_COUNTER

# Lazy — only created on first request, not at import time
# This saves ~200MB RAM at startup per worker
_llm = None

def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGroq(
            model=settings.LLM_MODEL,
            temperature=0.1,
            api_key=settings.GROQ_API_KEY,
        )
    return _llm


# ── NODE 1: Retrieve documents ─────────────────────
def retrieve(state: dict) -> dict:
    """Search vector database for relevant chunks."""
    start = time.time()
    docs = retrieve_relevant_chunks(state.get('rewritten_question') or state['question'])
    LATENCY_HISTOGRAM.labels(node='retrieve').observe(time.time() - start)
    RETRIEVAL_COUNTER.inc()
    return {'documents': docs}


# ── NODE 2: Grade whether docs are relevant ────────
GRADE_PROMPT = ChatPromptTemplate.from_template("""
You are grading if a document is relevant to a question.
Question: {question}
Document (first 400 chars): {doc}
Is this document relevant to the question? Answer ONLY "yes" or "no".
""")

def grade_documents(state: dict) -> dict:
    """Filter out documents that aren't relevant to the question."""
    graded = []
    for doc in state['documents']:
        result = get_llm().invoke(GRADE_PROMPT.format(
            question=state['question'],
            doc=doc['content'][:400]
        ))
        if 'yes' in result.content.lower():
            graded.append(doc)
    return {'graded_docs': graded}


# ── NODE 3: Rewrite query if no good docs found ────
REWRITE_PROMPT = ChatPromptTemplate.from_template("""
The question "{question}" did not find good documents.
Rewrite it to be clearer for a semantic search.
Return ONLY the improved question, nothing else.
""")

def rewrite_query(state: dict) -> dict:
    """Make the question better if retrieval failed."""
    result = get_llm().invoke(REWRITE_PROMPT.format(question=state['question']))
    return {
        'rewritten_question': result.content.strip(),
        'retries': state.get('retries', 0) + 1
    }


# ── NODE 4: Generate the final answer ──────────────
GENERATE_PROMPT = ChatPromptTemplate.from_template("""
You are a helpful assistant. Answer ONLY using the context below.
If the context does not have the answer, say exactly:
"I don't have enough information in the documents to answer this."
Do NOT make up any information.

Context:
{context}

Question: {question}

Answer:""")

def generate(state: dict) -> dict:
    """Generate an answer from the graded documents."""
    context = "\n\n---\n\n".join(d['content'] for d in state['graded_docs'])
    question = state.get('rewritten_question') or state['question']
    result = get_llm().invoke(GENERATE_PROMPT.format(context=context, question=question))
    return {'generation': result.content, 'gen_attempts': state.get('gen_attempts', 0) + 1}