from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rag_core.graph import rag_graph
from mlops.metrics import QUERY_COUNTER, ERROR_COUNTER
import uuid
import logging
logger = logging.getLogger(__name__)

class ChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question = request.data.get('question', '').strip()

        # Validate input
        if not question:
            return Response({'error': 'question is required'}, status=400)
        if len(question) > 2000:
            return Response({'error': 'question too long (max 2000 chars)'}, status=400)

        try:
            QUERY_COUNTER.inc()

            # Run the LangGraph pipeline
            result = rag_graph.invoke({
                'question':   question,
                'documents':  [],
                'graded_docs': [],
                'retries':    0,
                'user_id':    request.user.id,
                'session_id': str(uuid.uuid4()),
            })

            return Response({
                'answer':             result['generation'],
                'sources':            [d['source'] for d in result.get('graded_docs', [])],
                'hallucination_score': result.get('hallucination_score'),
            })

        except Exception as e:
            ERROR_COUNTER.inc()
            logger.exception("chat failed")
            return Response({'error': f"{type(e).__name__}: {e}"}, status=500)
            