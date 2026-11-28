from django.urls import path

from home_app import views as home_views

from . import views

urlpatterns = [
    path('', views.landing_view, name='landing'),
    path('browse/', home_views.public_browse_view, name='public_browse'),
    path('browse/medicine/<int:medicine_id>/', home_views.public_medicine_detail_view, name='public_medicine_detail'),
    path('browse/pharmacy/<int:pharmacy_id>/', home_views.public_pharmacy_detail_view, name='public_pharmacy_detail'),
    path('privacy/', views.info_view, {'slug': 'privacy'}, name='landing_privacy'),
    path('terms/', views.info_view, {'slug': 'terms'}, name='landing_terms'),
    path('security/', views.info_view, {'slug': 'security'}, name='landing_security'),
    path('contact/', views.info_view, {'slug': 'contact'}, name='landing_contact'),
]
