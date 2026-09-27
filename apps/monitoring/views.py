from django.http import HttpResponse, JsonResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from django.conf import settings

def health_view(request):
    return JsonResponse({'status': 'ok', 'service': 'rag-api'})

def metrics_view(request):
    token = request.headers.get('X-Metrics-Token', '')
    if token != settings.METRICS_TOKEN:
        return HttpResponse('Forbidden', status=403)
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)