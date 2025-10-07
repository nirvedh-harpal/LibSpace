from django.contrib import admin
from django.utils.html import format_html
from .models import LibrarySettings, Seat, Reservation

@admin.register(LibrarySettings)
class LibrarySettingsAdmin(admin.ModelAdmin):
    list_display = [
        'max_booking_duration',
        'max_advance_booking_days',
        'check_in_buffer',
        'max_active_reservations',
        'penalty_threshold',
        'penalty_duration_days',
    ]

    def has_add_permission(self, request):
        # Only allow one instance of settings
        return not LibrarySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of the settings
        return False


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['number', 'location', 'is_active', 'current_status']
    list_filter = ['is_active', 'location']
    search_fields = ['number', 'description']

    def current_status(self, obj):
        current_reservation = obj.reservation_set.filter(
            status__in=['reserved', 'checked_in']
        ).first()
        
        if not current_reservation:
            return format_html(
                '<span style="color: green;">Available</span>'
            )
        
        return format_html(
            '<span style="color: red;">Reserved by {} ({})</span>',
            current_reservation.user.username,
            current_reservation.get_status_display()
        )

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = [
        'student',
        'seat',
        'start_time',
        'end_time',
        'status',
        'check_in_time',
        'created_at'
    ]
    list_filter = ['status', 'start_time', 'check_in_time']
    search_fields = ['student__user__username', 'student__user__email', 'seat__number']
    readonly_fields = ['created_at', 'check_in_time']
    actions = ['mark_as_no_show', 'mark_as_completed']

    def mark_as_no_show(self, request, queryset):
        for reservation in queryset.filter(status='reserved'):
            reservation.status = 'no_show'
            reservation.save()
            reservation.user.studentprofile.increment_no_shows()
    mark_as_no_show.short_description = "Mark selected reservations as no-show"

    def mark_as_completed(self, request, queryset):
        queryset.filter(status='checked_in').update(status='completed')
    mark_as_completed.short_description = "Mark selected reservations as completed"
