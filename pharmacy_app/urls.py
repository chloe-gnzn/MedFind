from django.urls import path
from login_app import views as login_views
from . import views

urlpatterns = [
    path('login/', login_views.pharmacy_login_view, name='pharmacy_login'),
    path('forgot-password/', login_views.pharmacy_forgot_password_view, name='pharmacy_forgot_password'),
    path('register/', views.pharmacy_register_view, name='register_pharmacy'),
    path('logout/', login_views.logout_view, name='pharmacy_logout'),

    path('', views.dashboard_view, name='pharmacy_dashboard'),
    path('inventory/', views.inventory_list_view, name='pharmacy_inventory'),
    path('inventory/add/', views.inventory_add_view, name='inventory_add'),
    path('inventory/<int:inventory_id>/edit/', views.inventory_edit_view, name='inventory_edit'),
    path('inventory/<int:inventory_id>/quick-update/', views.inventory_quick_update_view, name='inventory_quick_update'),
    path('inventory/<int:inventory_id>/delete/', views.inventory_delete_view, name='inventory_delete'),
    path('hours/', views.hours_view, name='pharmacy_hours'),
    path('verification/', views.verification_view, name='pharmacy_verification'),
    path('verification/<int:verification_id>/cancel/', views.verification_cancel_view, name='verification_cancel'),
    path('profile/', views.profile_view, name='pharmacy_profile'),
    path('activity/', views.activity_view, name='pharmacy_activity'),
]
