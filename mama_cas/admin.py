from django.contrib import admin
from mama_cas.models import *

# Register your models here.

@admin.register(ServiceTicket)
class ServiceTicketAdmin(admin.ModelAdmin):
    list_display = ('get_username', 'service', 'primary',)
    search_fields = ('service', 'user__username',)

    def get_username(self, obj):
        return obj.user.username
    get_username.short_description = 'Username'
    get_username.admin_order_field = 'user__username'

@admin.register(ProxyTicket)
class ProxyTicketAdmin(admin.ModelAdmin):
    list_display = ('service', 'granted_by_pgt')
    search_fields = ('service',)

@admin.register(ProxyGrantingTicket)
class ProxyGrantingTicketAdmin(admin.ModelAdmin):
    list_display = ('iou','granted_by_st', 'granted_by_pt', 'TICKET_EXPIRE')
    search_fields = ('iou',)

