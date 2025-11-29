from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
from reservations.models import Seat, LibrarySettings
from django_ratelimit.decorators import ratelimit

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
