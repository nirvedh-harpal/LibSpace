# library_token_system/urls.py

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # API v1 endpoints
    path('api/v1/', include(([
        path('compartments/', include('compartments.urls')),
        path('reservations/', include('reservations.urls')),
    ], 'api'), namespace='v1')),
    # Keep legacy endpoints for backward compatibility
    path('', include('compartments.urls')),
    path('reservations/', include('reservations.urls')),
]
