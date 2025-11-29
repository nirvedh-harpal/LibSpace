import random
import datetime
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist

from reservations.tasks import send_email_task
from .models import Compartment, Student, OTP
from django.contrib.auth.models import User
from django.contrib import messages  # Import to use Django messages
from django.db import IntegrityError
from django.contrib.auth import logout
from django_ratelimit.decorators import ratelimit

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, "Login successfully!")
            if user.is_staff:
                return redirect('security_dashboard')
            else:
                return redirect('dashboard')
        else:
            messages.warning(request, "Incorrect username or password")
            return render(request, 'login.html')
    return render(request, 'login.html')

@login_required
def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def security_dashboard(request):
    if not request.user.is_staff:
        return redirect('login')
    compartments = Compartment.objects.all()
    all_count = compartments.count()
    empty_count = compartments.filter(is_empty=True).count()
    occupied_count = compartments.filter(is_empty=False).count()
    context = {
        'compartments': compartments,
        'all_count': all_count,
        'empty_count': empty_count,
        'occupied_count': occupied_count,
    }
    return render(request, 'security_dashboard.html', context)

@login_required
def student_dashboard(request): 
    try:
        student = request.user.student
        try:
            compartment = student.compartment  # Retrieve the student's compartment
            otp = OTP.objects.filter(student=student).last()  # Retrieve the latest OTP for the student
            return render(request, 'student_dashboard.html', {'student': student, 'compartment': compartment, 'otp': otp})
        except ObjectDoesNotExist:
            return render(request, 'student_dashboard.html', {'student': student, 'error': 'No compartment assigned to you.'})
    except Student.DoesNotExist:
        return redirect('login')

def register(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        roll_number = request.POST['roll_number']
        branch = request.POST['branch']
        
        # Check if the username already exists
        if User.objects.filter(username=username).exists():
            messages.warning(request, "Username already exists. Please choose a different username.")
            return render(request, 'register.html')

        # Check if the roll number already exists
        if Student.objects.filter(roll_number=roll_number).exists():
            messages.warning(request, "Roll number already exists. Please check your roll number.")
            return render(request, 'register.html')
        
        try:
            # Create the user and the student
            user = User.objects.create_user(username=username, email=email, password=password)
            student = Student.objects.create(user=user, roll_number=roll_number, branch=branch)
            messages.success(request, "Registration successful! Please log in.")
            return redirect('login')  # Redirect to login page after registration
        except IntegrityError:
            messages.warning(request, "An error occurred during registration. Please try again.")
            return render(request, 'register.html')
    
    return render(request, 'register.html')


@login_required
def generate_otp(request, compartment):
    return str(random.randint(100000, 999999))

@login_required
@ratelimit(key='ip', rate='20/m', block=True)
def assign_compartment(request):
    if not request.user.is_staff:
        return redirect('login')
    
    if request.method == 'POST':
        roll_number = request.POST.get('roll_number')
        compartment_number = request.POST.get('compartment_number')
        
        try:
            student = Student.objects.get(roll_number=roll_number)
        except Student.DoesNotExist:
            messages.warning(request, f"No student found with roll number {roll_number}")
            return redirect('security_dashboard')
        
        # Check if the student already has a compartment assigned
        if Compartment.objects.filter(student=student).exists():
            messages.warning(request, f"Student with roll number {roll_number} already has a compartment assigned.")
            return redirect('security_dashboard')
        
        try:
            compartment = Compartment.objects.get(number=compartment_number)
        except Compartment.DoesNotExist:
            messages.warning(request, f"No compartment found with number {compartment_number}")
            return redirect('security_dashboard')
        
        otp = generate_otp(request, compartment)
        compartment.student = student
        compartment.is_empty = False
        compartment.save()

        # Save OTP to the OTP model
        otp_instance = OTP(student=student, code=otp, compartment=compartment)
        otp_instance.save()
        
        # Send OTP email to the student
        subject = 'Your OTP for Compartment Deallocation'
        message = f'Dear {student.user.username},\n\nYour OTP for the compartment {compartment.number} is {otp}. Please use this OTP for deallocation.'
        email_from = 'hnirvedh@gmail.com'  # Replace with your email
        recipient_list = [student.user.email]
        send_email_task.delay(subject, message, recipient_list, email_from)

        return redirect('security_dashboard')
    
    return redirect('security_dashboard')

@login_required
def deallocate_compartment(request, compartment_id):
    if not request.user.is_staff:
        return redirect('login')
    if request.method == 'POST':
        otp_input = request.POST.get('otp')
        compartment = Compartment.objects.get(id=compartment_id)
        student = compartment.student
        otp = OTP.objects.get(student=student)

        if otp.code == otp_input and otp.compartment == compartment:
            compartment.student = None
            compartment.is_empty = True
            compartment.save()
            otp.delete()

            # Send email notification to the student
            subject = 'Compartment Deallocated'
            message = f'Dear {student.user.username},\n\nYour compartment {compartment.number} has been successfully deallocated.'
            email_from = 'hnirvedh@gmail.com'  # Replace with your email
            recipient_list = [student.user.email]
            send_email_task.delay(subject, message, recipient_list, email_from)
            messages.success(request, f"Compartment {compartment.number} deallocated successfully!")
            return redirect('security_dashboard')
        else:
            messages.warning(request, "Invalid OTP!")
            return redirect('security_dashboard')
    return redirect('security_dashboard')
