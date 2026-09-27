import bleach, hashlib, json
from django.core.cache import cache
from django.http import JsonResponse


class RateLimitMiddleware:
    """Block users who send too many requests (30 per minute)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api/'):
            key = self._make_key(request)
            if not self._is_allowed(key, limit=30, window=60):
                return JsonResponse(
                    {'error': 'Too many requests. Wait 1 minute.'},
                    status=429
                )
        return self.get_response(request)

    def _make_key(self, request):
        user_id = getattr(request.user, 'id', 'anon')
        ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META['REMOTE_ADDR']).split(',')[0].strip()
        raw = f"{user_id}:{ip}"
        return f"rl:{hashlib.md5(raw.encode()).hexdigest()}"

    def _is_allowed(self, key: str, limit: int, window: int) -> bool:
        count = cache.get(key, 0)
        if count >= limit:
            return False
        cache.set(key, count + 1, timeout=window)
        return True


class InputSanitizationMiddleware:
    """Remove dangerous HTML/JS from all incoming JSON data."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if 'application/json' in request.content_type and request.body:
            try:
                data = json.loads(request.body)
                cleaned = self._clean(data)
                request._body = json.dumps(cleaned).encode()
            except Exception:
                pass
        return self.get_response(request)

    def _clean(self, data):
        if isinstance(data, dict):
            return {k: self._clean(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._clean(i) for i in data]
        elif isinstance(data, str):
            return bleach.clean(data, tags=[], strip=True)
        return data