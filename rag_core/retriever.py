from pgvector.django import CosineDistance
from apps.documents.models import DocumentChunk
from .embedder import embed_text
from django.conf import settings


def retrieve_relevant_chunks(query: str, top_k: int = None) -> list:
    """
    Find the most relevant text chunks for a user's question.
    1. Convert question to vector
    2. Search database for similar vectors
    3. Return the top results
    """
    k = top_k or settings.RETRIEVAL_TOP_K
    query_vector = embed_text(query)

    chunks = (
        DocumentChunk.objects
        .annotate(distance=CosineDistance('embedding', query_vector))
        .filter(distance__lt=0.7)   # only close matches
        .order_by('distance')[:k]
    )

    return [
        {
            'content': chunk.content,
            'source':  chunk.document.title,
            'score':   round(1 - chunk.distance, 3),
            'chunk_id': chunk.id,
        }
        for chunk in chunks
    ]