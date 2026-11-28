from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('landing_app.urls')),
    path('login/', include('login_app.urls')),
    path('register/', include('register_app.urls')),
    path('home/', include('home_app.urls')),
    path('pharmacy-portal/', include('pharmacy_app.urls')),
    path('manage/', include('admin_app.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
