from django.contrib import admin
from lipad_sso.models import *

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('username', 'organization', 'organization_type')
    search_fields = ('username', 'organization', 'organization_type')

