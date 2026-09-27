from django.db import models
from pgvector.django import VectorField, HnswIndex

class Document(models.Model):
    """Stores info about uploaded PDF files."""
    title      = models.CharField(max_length=500)
    file_key   = models.CharField(max_length=500)  # S3 file path
    created_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey('auth.User', on_delete=models.CASCADE)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-created_at']


class DocumentChunk(models.Model):
    """Stores a piece of text with its embedding vector."""
    document    = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    content     = models.TextField()         # the actual text
    chunk_index = models.IntegerField()      # which chunk number
    embedding   = VectorField(dimensions=384)   # 384 dims — all-MiniLM-L6-v2 (free, runs locally)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            HnswIndex(
                name='chunk_embed_hnsw_idx',
                fields=['embedding'],
                m=16, ef_construction=64,
                opclasses=['vector_cosine_ops']
            )
        ]