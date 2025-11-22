from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from compartments import views

urlpatterns = [
    path('', lambda request: redirect('login/', permanent=True)),
    path('admin/', admin.site.urls),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),  # Add this line
    path('security_dashboard/', views.security_dashboard, name='security_dashboard'),
    path('student_dashboard/', views.student_dashboard, name='student_dashboard'),
    path('assign_compartment/', views.assign_compartment, name='assign_compartment'),   
    path('deallocate_compartment/<int:compartment_id>/', views.deallocate_compartment, name='deallocate_compartment'),
    path('register/', views.register, name='register'),
]
