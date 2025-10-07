# library_token_system/urls.py

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('compartments.urls')),
    path('reservations/', include('reservations.urls')),
]
