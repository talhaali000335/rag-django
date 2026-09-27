from celery import shared_task
from .models import Document, DocumentChunk
from rag_core.embedder import embed_text, chunk_text
import boto3, tempfile
from pypdf import PdfReader
from django.conf import settings

@shared_task(bind=True, max_retries=3)
def ingest_document(self, document_id: int):
    """Download PDF from S3, split into chunks, embed each chunk."""
    doc = Document.objects.get(id=document_id)
    s3 = boto3.client('s3')

    # Download the PDF to a temp file
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        s3.download_fileobj(settings.AWS_STORAGE_BUCKET_NAME, doc.file_key, f)
        f.seek(0)
        reader = PdfReader(f)
        full_text = ' '.join(
            page.extract_text() for page in reader.pages
            if page.extract_text()
        )

    # Split text into chunks and embed
    chunks = chunk_text(full_text)
    chunk_objects = []
    for i, text in enumerate(chunks):
        vector = embed_text(text)
        chunk_objects.append(DocumentChunk(
            document=doc,
            content=text,
            chunk_index=i,
            embedding=vector,
        ))

    DocumentChunk.objects.bulk_create(chunk_objects, batch_size=50)
    return {'status': 'done', 'chunks_created': len(chunk_objects)}