from django.urls import path
from . import views

app_name = "reservations_v1" 
urlpatterns = [
    path('seats/', views.seat_list, name='seat_list'),
]