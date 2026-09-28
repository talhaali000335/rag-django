from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView          # ← ADD THIS
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('',           TemplateView.as_view(template_name='index.html')),  # ← ADD THIS
    path('admin/',         admin.site.urls),
    path('api/token/',     TokenObtainPairView.as_view()),
    path('api/token/refresh/', TokenRefreshView.as_view()),
    path('api/chat/',      include('apps.chat.urls')),
    path('api/documents/', include('apps.documents.urls')),
    path('health/',        include('apps.monitoring.urls')),
]