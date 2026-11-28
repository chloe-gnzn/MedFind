from django.contrib import admin

from .models import Inventory, OperatingHours, Pharmacy, PharmacyVerification, Reservation


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('inventory_id', 'pharmacy', 'medicine', 'price', 'availability_status', 'stock_quantity')
    list_filter = ('availability_status', 'pharmacy')


@admin.register(OperatingHours)
class OperatingHoursAdmin(admin.ModelAdmin):
    list_display = ('hours_id', 'pharmacy', 'days_of_week', 'opening_time', 'closing_time', 'is_closed')


@admin.register(PharmacyVerification)
class PharmacyVerificationAdmin(admin.ModelAdmin):
    list_display = ('verification_id', 'pharmacy', 'status', 'reviewed_by', 'reviewed_at')
    list_filter = ('status',)


@admin.register(Pharmacy)
class PharmacyAdmin(admin.ModelAdmin):
    list_display = ('pharmacy_id', 'business_name', 'email', 'verification_status', 'is_active')
    list_filter = ('verification_status', 'is_active')
    search_fields = ('business_name', 'email')
    exclude = ('password_hash',)

    def has_add_permission(self, request):
        return False  # register through the app so passwords get hashed


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('reservation_code', 'user', 'pharmacy', 'medicine', 'quantity', 'status', 'expires_at')
    list_filter = ('status', 'pharmacy')
    search_fields = ('reservation_code', 'user__email', 'medicine__medicine_name', 'pharmacy__business_name')
