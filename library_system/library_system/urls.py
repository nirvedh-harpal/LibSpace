# library_token_system/urls.py

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('compartments.urls')),
    path('reservations/', include('reservations.urls')),
    path("v1/reservations/", include(("reservations.v1.urls", "reservations_v1"), namespace="reservations_v1")),
]
