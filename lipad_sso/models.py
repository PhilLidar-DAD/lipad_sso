from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import ugettext as _

class Profile(AbstractUser):
	organization = models.CharField(_('Organization Name'), max_length=255, blank=True, null=True)
	organization_type = models.CharField(_('Organization Type'), max_length=255, blank=True, null=True)
