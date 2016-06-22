from django.conf.urls import include, url
from django.contrib import admin
from django.views.generic import RedirectView

import mama_cas

#urlpatterns = patterns('',
    # Examples:
    # url(r'^$', 'lipad_sso.views.home', name='home'),
    # url(r'^blog/', include('blog.urls')),

#    url(r'^admin/', include(admin.site.urls)),
#)

urlpatterns = [
	url(r'^admin/', admin.site.urls),
    url(r'^', include('mama_cas.urls')),
    url(r'^cas/',include('mama_cas.urls')),
    url(r'^$', RedirectView.as_view(url='/login')),

]
