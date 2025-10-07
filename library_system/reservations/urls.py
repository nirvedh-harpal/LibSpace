from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('seats/', views.seat_list, name='seat_list'),
    path('seats/<int:seat_id>/reserve/', views.create_reservation, name='create_reservation'),
    path('reservation/<int:reservation_id>/check-in/', views.check_in, name='check_in'),
    path('reservation/<int:reservation_id>/cancel/', views.cancel_reservation, name='cancel_reservation'),
]