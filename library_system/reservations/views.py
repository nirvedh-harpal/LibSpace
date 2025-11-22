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
from .models import Seat, Reservation, LibrarySettings, Payment
from compartments.models import OTP, Student
from django_ratelimit.decorators import ratelimit
from django.db import transaction
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
import stripe
import json
from django.db import models
from django.urls import reverse

stripe.api_key = settings.STRIPE_SECRET_KEY

@login_required
@ratelimit(key='ip', rate='10/m', block=True)
def dashboard(request):
    if getattr(request, 'limited', False):
        return render(request, 'reservations/error.html', {'message': 'Too many attempts. Please try again later.'}, status=429)
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

    # Get past reservations
    past_page = request.GET.get('past_page', 1)
    past_page_cache_key = f"reservations_past_page_{student.user.id}_{past_page}"
    past_reservations = cache.get(past_page_cache_key)
    if past_reservations is None:
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
        past_reservations = past_paginator.get_page(past_page)
        cache.set(past_page_cache_key, past_reservations, 60)  # Cache for 60 seconds

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

    # Get fines from the Student model
    fines = student.fines

    context = {
        'current_reservations': current_reservations,
        'past_reservations': past_reservations,
        'student': student,
        'compartment': compartment,
        'otp': otp,
        'fines': fines,
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

    print("Debugging create_reservation:")
    print("Request method:", request.method)
    print("Seat ID:", seat_id)
    print("POST data:", request.POST)

    try:
        with transaction.atomic():
            seat = Seat.objects.select_for_update().get(id=seat_id)
            print("Seat fetched:", seat)

            start_time_str = request.POST.get('start_time')
            duration = request.POST.get('duration')
            print("Start time:", start_time_str, "Duration:", duration)

            start_time = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
            start_time = timezone.make_aware(start_time)
            duration = int(duration)
            end_time = start_time + timedelta(minutes=duration)

            overlapping_reservations = Reservation.objects.filter(
                seat=seat,
                start_time__lt=end_time,
                end_time__gt=start_time
            )
            print("Overlapping reservations:", overlapping_reservations)

            if overlapping_reservations.exists():
                messages.error(request, "The seat is already reserved for the selected time range.")
                return redirect('seat_list')

            reservation = Reservation(
                student=Student.objects.get(user=request.user),
                seat=seat,
                start_time=start_time,
                end_time=end_time
            )
            reservation.save()
            print("Reservation created:", reservation)

        messages.success(request, "Reservation created successfully!")
        return redirect('dashboard')

    except ValidationError as e:
        print("Validation error:", e)
        messages.error(request, str(e))
    except Seat.DoesNotExist:
        print("Seat does not exist error")
        messages.error(request, "The selected seat does not exist.")
    except Exception as e:
        print("General exception:", e)
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

@login_required
def initiate_payment(request):
    if request.method == 'POST':
        amount = request.POST.get('amount')
        if not amount:
            messages.error(request, "Amount is required.")
            return redirect('dashboard')

        try:
            student = Student.objects.get(user=request.user)
            amount = float(amount)
            
            # Validate amount doesn't exceed fines
            if amount > float(student.fines):
                messages.error(request, f"Payment amount cannot exceed outstanding fines of ₹{student.fines}")
                return redirect('dashboard')
            
            # Create Stripe Checkout Session with INR currency
            # Note: Stripe requires amounts in the smallest currency unit (paise for INR)
            # So we multiply by 100 to convert from rupees to paise
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price_data': {
                            'currency': 'inr',  # Indian Rupees
                            'unit_amount': int(amount * 100),  # Convert rupees to paise
                            'product_data': {
                                'name': 'Library Fine Payment',
                                'description': f'Fine payment for student {student.user.get_full_name()}',
                            },
                        },
                        'quantity': 1,
                    }
                ],
                mode='payment',
                success_url=request.build_absolute_uri(reverse('payment_success')),
                cancel_url=request.build_absolute_uri(reverse('payment_failure')),
                customer_email=request.user.email,
                metadata={
                    'student_id': student.id,
                    'user_id': request.user.id,
                }
            )

            # Create Payment record to track the transaction
            payment = Payment.objects.create(
                student=student,
                amount=amount,
                status='pending',
                stripe_session_id=checkout_session.id
            )

            return redirect(checkout_session.url)
        except Exception as e:
            messages.error(request, f"Payment initiation failed: {str(e)}")
            return redirect('dashboard')

@csrf_exempt
def payment_webhook(request):
    """
    Webhook handler for Stripe payment status updates.
    Stripe sends payment status updates to this endpoint.
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError:
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    except stripe.error.SignatureVerificationError:
        return JsonResponse({'error': 'Invalid signature'}, status=400)

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        session_id = session['id']
        
        # Find the payment associated with this session
        try:
            payment = Payment.objects.get(stripe_session_id=session_id)
            
            # Update the current payment to completed
            payment.status = 'completed'
            payment.save()
            
            # Clear student fines based on payment amount
            payment.clear_student_fines()
            
        except Payment.DoesNotExist:
            pass

    elif event['type'] == 'checkout.session.async_payment_failed':
        session = event['data']['object']
        session_id = session['id']
        
        # Update payment status to failed
        Payment.objects.filter(stripe_session_id=session_id).update(status='failed')

    return JsonResponse({'status': 'success'})

@login_required
def payment_success(request):
    """
    Redirect page after successful payment from Stripe.
    The actual payment status is updated via the webhook.
    """
    messages.success(request, "Payment completed successfully! Your account has been updated.")
    return redirect('dashboard')

@login_required
def payment_failure(request):
    """
    Redirect page after failed payment from Stripe.
    """
    messages.error(request, "Payment failed. Please try again.")
    return redirect('dashboard')
