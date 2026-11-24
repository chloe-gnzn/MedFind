from django.urls import path
from login_app import views as login_views
from . import views

urlpatterns = [
    path('login/', login_views.admin_login_view, name='admin_login'),
    path('logout/', login_views.logout_view, name='admin_logout'),

    path('', views.dashboard_view, name='admin_dashboard'),

    path('verifications/', views.verifications_view, name='admin_verifications'),
    path('verifications/<int:verification_id>/', views.verification_review_view, name='admin_verification_review'),

    path('pharmacies/', views.pharmacies_view, name='admin_pharmacies'),
    path('pharmacies/<int:pharmacy_id>/toggle/', views.pharmacy_toggle_view, name='admin_pharmacy_toggle'),
    path('users/', views.users_view, name='admin_users'),

    path('categories/', views.categories_view, name='admin_categories'),
    path('categories/add/', views.category_form_view, name='admin_category_add'),
    path('categories/<int:category_id>/edit/', views.category_form_view, name='admin_category_edit'),
    path('categories/<int:category_id>/delete/', views.category_delete_view, name='admin_category_delete'),

    path('medicines/', views.medicines_view, name='admin_medicines'),
    path('medicines/add/', views.medicine_form_view, name='admin_medicine_add'),
    path('medicines/<int:medicine_id>/edit/', views.medicine_form_view, name='admin_medicine_edit'),
    path('medicines/<int:medicine_id>/delete/', views.medicine_delete_view, name='admin_medicine_delete'),

    path('inventory/', views.inventory_monitor_view, name='admin_inventory'),   # SQL JOIN screen
    path('reports/', views.stock_report_view, name='admin_reports'),            # SQL SUBQUERY screen

    path('activity/', views.activity_view, name='admin_activity'),
]
