from django.contrib import admin

from .models import Booking, BookingSettings, MeetingType


@admin.register(BookingSettings)
class BookingSettingsAdmin(admin.ModelAdmin):
    list_display = ["__str__", "is_enabled", "timezone", "updated_at"]

    def has_add_permission(self, request):
        return not BookingSettings.objects.exists()


@admin.register(MeetingType)
class MeetingTypeAdmin(admin.ModelAdmin):
    list_display = ["title", "duration_minutes", "is_active", "order"]
    list_editable = ["is_active", "order"]
    prepopulated_fields = {"slug": ["title"]}


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["start", "title", "name", "email", "status"]
    list_filter = ["status", "title"]
    search_fields = ["name", "email", "company", "notes"]
    date_hierarchy = "start"
    readonly_fields = ["uid", "sequence", "cancel_token", "created_at", "cancelled_at"]
