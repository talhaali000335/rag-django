from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser
from .models import Document
from .tasks import ingest_document
import boto3, uuid
from django.conf import settings

class DocumentUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'No file provided'}, status=400)
        if not file.name.endswith('.pdf'):
            return Response({'error': 'Only PDF files allowed'}, status=400)

        # Upload to S3
        s3 = boto3.client('s3')
        file_key = f"docs/{uuid.uuid4()}/{file.name}"
        s3.upload_fileobj(file, settings.AWS_STORAGE_BUCKET_NAME, file_key)

        # Save document record
        doc = Document.objects.create(
            title=file.name,
            file_key=file_key,
            uploaded_by=request.user
        )

        # Queue background processing
        ingest_document.delay(doc.id)

        return Response({
            'id': doc.id,
            'message': 'Document uploaded. Processing in background.'
        }, status=201)