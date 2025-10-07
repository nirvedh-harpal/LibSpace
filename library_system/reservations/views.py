from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from datetime import datetime, timedelta
from .models import Seat, Reservation, LibrarySettings
from compartments.models import OTP, Student
from django_ratelimit.decorators import ratelimit

@login_required
@ratelimit(key='ip', rate='10/m', block=True)
def dashboard(request):
    if getattr(request, 'limited', False):
        return render(request, 'reservations/error.html', {'message': 'Too many registration attempts. Please try again later.'}, status=429)
    student = Student.objects.get(user=request.user)
    if student.check_restrictions():
        messages.error(request, "Your booking privileges are currently restricted due to multiple no-shows.")
        return render(request, 'reservations/dashboard.html', {'restricted': True})

    # Get active reservations (reserved or checked in)
    current_reservations = Reservation.objects.filter(
        student=student,
        status__in=['reserved', 'checked_in'],
        end_time__gt=timezone.now()
    ).order_by('start_time')

    # Get all past reservations (completed, cancelled, and no_show)
    past_reservations_qs = Reservation.objects.filter(
        student=student,
    ).filter(
        Q(end_time__lt=timezone.now()) |  # Past reservations
        Q(status__in=['cancelled', 'no_show', 'checked_in'])  # Cancelled or no_show reservations
    ).exclude(
        id__in=current_reservations.values_list('id', flat=True)
    ).order_by('-start_time')
    
    # Add pagination for past reservations
    past_paginator = Paginator(past_reservations_qs, 2)  # Show 10 per page
    past_page = request.GET.get('past_page')
    past_reservations = past_paginator.get_page(past_page)

    # Cache compartment and OTP for this user for 60 seconds
    compartment_cache_key = f"compartment_user_{student.user.id}"
    otp_cache_key = f"otp_user_{student.user.id}"
    compartment = cache.get(compartment_cache_key)
    if compartment is None:
        compartment = student.compartment
        cache.set(compartment_cache_key, compartment, 60)
    otp = cache.get(otp_cache_key)
    if otp is None:
        otp = OTP.objects.filter(student=student).last()
        cache.set(otp_cache_key, otp, 60)

    context = {
        'current_reservations': current_reservations,
        'past_reservations': past_reservations,
        'student': student,
        'compartment': compartment,
        'otp': otp,
    }
    return render(request, 'reservations/dashboard.html', context)

@login_required
@ratelimit(key='ip', rate='10/m', block=True)
def seat_list(request):
    start_time_str = request.GET.get('start_time')
    duration = request.GET.get('duration')

    # Always include current time in context
    context = {
        'now': timezone.localtime(timezone.now())
    }
    
    if not (start_time_str and duration):
        return render(request, 'reservations/seat_list.html', context)

    try:
        start_time = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
        start_time = timezone.make_aware(start_time)
        duration = int(duration)
        end_time = start_time + timedelta(minutes=duration)

        settings = LibrarySettings.get_settings()
        if duration > settings.max_booking_duration:
            messages.error(request, f"Maximum booking duration is {settings.max_booking_duration} minutes")
            return render(request, 'reservations/seat_list.html')

        available_seats = Seat.get_available_seats(start_time, end_time)
        context = {
            'seats': available_seats,
            'start_time': start_time,
            'end_time': end_time,
            'now': timezone.localtime(timezone.now())
        }
        return render(request, 'reservations/seat_list.html', context)

    except (ValueError, TypeError):
        messages.error(request, "Invalid date/time or duration")
        return render(request, 'reservations/seat_list.html')

@login_required
@ratelimit(key='ip', rate='5/m', block=True)
def create_reservation(request, seat_id):
    if request.method != 'POST':
        return redirect('seat_list')

    print("Creating reservation for seat:", seat_id)
    print("POST data:", request.POST)
    
    seat = get_object_or_404(Seat, id=seat_id)
    start_time_str = request.POST.get('start_time')
    duration = request.POST.get('duration')

    try:
        start_time = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
        start_time = timezone.make_aware(start_time)
        duration = int(duration)
        end_time = start_time + timedelta(minutes=duration)

        reservation = Reservation(
            student=Student.objects.get(user=request.user),
            seat=seat,
            start_time=start_time,
            end_time=end_time
        )
        reservation.save()

        messages.success(request, "Reservation created successfully!")
        return redirect('dashboard')

    except ValidationError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, "Failed to create reservation")

    return redirect('seat_list')

@login_required
@ratelimit(key='ip', rate='3/m', block=True)
def check_in(request, reservation_id):
    student = Student.objects.get(user=request.user)
    reservation = get_object_or_404(
        Reservation,
        id=reservation_id,
        student=student
    )

    try:
        if request.method == 'POST':
            otp = request.POST.get('otp')
            reservation.check_in(otp)
            messages.success(request, "Check-in successful!")
            return redirect('dashboard')
        else:
            if not reservation.can_check_in():
                messages.warning(request, "Check-in not allowed at this time")
                return redirect('dashboard')
            
            reservation.generate_otp()
            return render(request, 'reservations/check_in.html', {'reservation': reservation})

    except ValidationError as e:
        error_message = str(e)
        if error_message.startswith('[') and error_message.endswith(']'):
            error_message = error_message[2:-2]  # Remove ['...']
        messages.error(request, error_message)
    return redirect('dashboard')

@login_required
@ratelimit(key='ip', rate='5/m', block=True)
def cancel_reservation(request, reservation_id):
    if request.method != 'POST':
        return redirect('dashboard')

    student = Student.objects.get(user=request.user)
    reservation = get_object_or_404(
        Reservation,
        id=reservation_id,
        student=student,
        status='reserved'
    )

    reservation.status = 'cancelled'
    reservation.save()
    messages.success(request, "Reservation cancelled successfully")
    return redirect('dashboard')
