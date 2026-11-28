from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('search/', views.search_view, name='search'),
    path('medicine/<int:medicine_id>/', views.medicine_detail_view, name='medicine_detail'),
    path('pharmacy/<int:pharmacy_id>/', views.pharmacy_detail_view, name='pharmacy_detail'),
    path('favorites/', views.favorites_view, name='favorites'),
    path('favorites/toggle/<str:kind>/<int:obj_id>/', views.toggle_favorite_view, name='toggle_favorite'),
    path('history/', views.history_view, name='history'),
    path('history/<int:search_id>/delete/', views.delete_history_item_view, name='delete_history_item'),
    path('history/clear/', views.clear_history_view, name='clear_history'),
    path('profile/', views.profile_view, name='user_profile'),
]
