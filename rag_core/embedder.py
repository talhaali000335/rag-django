from sentence_transformers import SentenceTransformer
from django.core.cache import cache
import hashlib

# Free local model — runs on your machine, zero API cost
_model = None

def get_model():
    """Load model once and reuse (lazy loading)."""
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2')  # 384-dim, fast, free
    return _model


def embed_text(text: str) -> list:
    """Convert text to a vector. Uses Redis cache to avoid recomputing."""
    cache_key = f"embed:{hashlib.md5(text.encode()).hexdigest()}"
    cached = cache.get(cache_key)
    if cached:
        return cached  # return from cache, saves compute time

    # Run embedding locally — no API call, no cost
    model = get_model()
    vector = model.encode(text.strip()[:512]).tolist()  # max 512 tokens
    cache.set(cache_key, vector, timeout=86400)  # cache 24 hours
    return vector


def chunk_text(text: str, chunk_size=400, overlap=50) -> list:
    """Split long text into overlapping chunks."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = ' '.join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks