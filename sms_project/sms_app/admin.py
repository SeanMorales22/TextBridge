from django.contrib import admin

from .models import Contact, SmsMessage


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_number", "created_at")
    search_fields = ("name", "phone_number")


@admin.register(SmsMessage)
class SmsMessageAdmin(admin.ModelAdmin):
    list_display = ("recipient", "status", "num_segments", "error_code", "created_at")
    list_filter = ("status",)
    search_fields = ("recipient", "body", "provider_sid")  # provider_sid = gateway message ID
    readonly_fields = ("provider_sid", "created_at", "updated_at")
