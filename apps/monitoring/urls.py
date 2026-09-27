from django.urls import path
from .views import health_view, metrics_view

urlpatterns = [
    path('',        health_view,  name='health'),
    path('metrics/', metrics_view, name='metrics'),
]