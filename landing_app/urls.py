from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing_view, name='landing'),
    path('privacy/', views.info_view, {'slug': 'privacy'}, name='landing_privacy'),
    path('terms/', views.info_view, {'slug': 'terms'}, name='landing_terms'),
    path('security/', views.info_view, {'slug': 'security'}, name='landing_security'),
    path('contact/', views.info_view, {'slug': 'contact'}, name='landing_contact'),
]
