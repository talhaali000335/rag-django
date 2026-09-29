from typing import TypedDict
from langgraph.graph import StateGraph, END
from .nodes import retrieve, grade_documents, rewrite_query, generate
from .hallucination import hallucination_check_node


class RAGState(TypedDict, total=False):
    question: str
    rewritten_question: str
    documents: list
    graded_docs: list
    generation: str
    hallucination_score: float
    retries: int
    gen_attempts: int
    user_id: int
    session_id: str


def decide_after_grading(state: dict) -> str:
    """If no relevant docs found AND we haven't retried twice → rewrite query."""
    if len(state.get('graded_docs', [])) == 0 and state.get('retries', 0) < 2:
        return 'rewrite'
    return 'generate'


def decide_after_hallucination(state: dict) -> str:
    """If answer is hallucinated AND we haven't regenerated twice → regenerate."""
    if state.get('hallucination_score', 0) > 0.7 and state.get('gen_attempts', 0) < 2:
        return 'generate'
    return 'end'


def build_rag_graph():
    g = StateGraph(RAGState)

    g.add_node('retrieve',            retrieve)
    g.add_node('grade_documents',     grade_documents)
    g.add_node('rewrite_query',       rewrite_query)
    g.add_node('generate',            generate)
    g.add_node('hallucination_check', hallucination_check_node)

    g.set_entry_point('retrieve')
    g.add_edge('retrieve', 'grade_documents')
    g.add_conditional_edges(
        'grade_documents',
        decide_after_grading,
        {'rewrite': 'rewrite_query', 'generate': 'generate'},
    )
    g.add_edge('rewrite_query', 'retrieve')
    g.add_edge('generate', 'hallucination_check')
    g.add_conditional_edges(
        'hallucination_check',
        decide_after_hallucination,
        {'generate': 'generate', 'end': END},
    )
    return g.compile()


rag_graph = build_rag_graph()