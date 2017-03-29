from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models

class Profile(AbstractBaseUser):
	organization = models.CharField(_('Organization Name'), max_length=255, required=False, blank=True, null=True)
	organization_type = models.CharField(_('Organization Type'), max_length=255, required=False, blank=True, null=True)
