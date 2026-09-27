from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('admin/',         admin.site.urls),
    path('api/token/',     TokenObtainPairView.as_view()),
    path('api/token/refresh/', TokenRefreshView.as_view()),
    path('api/chat/',      include('apps.chat.urls')),
    path('api/documents/', include('apps.documents.urls')),
    path('health/',        include('apps.monitoring.urls')),
]