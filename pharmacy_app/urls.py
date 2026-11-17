from django.urls import path
from login_app import views as login_views
from . import views

urlpatterns = [
    path('login/', login_views.pharmacy_login_view, name='pharmacy_login'),
    path('register/', views.pharmacy_register_view, name='register_pharmacy'),
    path('logout/', login_views.logout_view, name='pharmacy_logout'),

    path('', views.dashboard_view, name='pharmacy_dashboard'),
    path('inventory/', views.inventory_list_view, name='pharmacy_inventory'),
    path('inventory/add/', views.inventory_add_view, name='inventory_add'),
    path('inventory/<int:inventory_id>/edit/', views.inventory_edit_view, name='inventory_edit'),
    path('inventory/<int:inventory_id>/delete/', views.inventory_delete_view, name='inventory_delete'),
    path('hours/', views.hours_view, name='pharmacy_hours'),
    path('verification/', views.verification_view, name='pharmacy_verification'),
]
