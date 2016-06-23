import logging
import warnings

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.utils.module_loading import import_string
from django.utils.translation import ugettext_lazy as _

from mama_cas.models import ServiceTicket
from mama_cas.models import ProxyTicket
from mama_cas.models import ProxyGrantingTicket
from mama_cas.exceptions import InvalidTicketSpec
from mama_cas.exceptions import ValidationError
from mama_cas.utils import get_config

from pprint import pprint

logger = logging.getLogger(__name__)


def validate_service_ticket(service, ticket, pgturl, renew=False, require_https=False):
    """
    Validate a service ticket string. Return a triplet containing a
    ``ServiceTicket`` and an optional ``ProxyGrantingTicket``, or a
    ``ValidationError`` if ticket validation failed.
    """
    logger.debug("Service validation request received for %s" % ticket)
    # Check for proxy tickets passed to /serviceValidate
    if ticket and ticket.startswith(ProxyTicket.TICKET_PREFIX):
        e = InvalidTicketSpec('Proxy tickets cannot be validated with /serviceValidate')
        logger.warning("%s %s" % (e.code, e))
        return None, None, e

    try:
        st = ServiceTicket.objects.validate_ticket(ticket, service, renew=renew, require_https=require_https)
    except ValidationError as e:
        logger.warning("%s %s" % (e.code, e))
        return None, None, e
    else:
        if pgturl:
            logger.debug("Proxy-granting ticket request received for %s" % pgturl)
            pgt = ProxyGrantingTicket.objects.create_ticket(service, pgturl, user=st.user, granted_by_st=st)
        else:
            pgt = None
        return st, pgt, None


def validate_proxy_ticket(service, ticket, pgturl):
    """
    Validate a proxy ticket string. Return a 4-tuple containing a
    ``ProxyTicket``, an optional ``ProxyGrantingTicket`` and a list
    of proxies through which authentication proceeded, or a
    ``ValidationError`` if ticket validation failed.
    """
    logger.debug("Proxy validation request received for %s" % ticket)
    try:
        pt = ProxyTicket.objects.validate_ticket(ticket, service)
    except ValidationError as e:
        logger.warning("%s %s" % (e.code, e))
        return None, None, None, e
    else:
        # Build a list of all services that proxied authentication,
        # in reverse order of which they were traversed
        proxies = [pt.service]
        prior_pt = pt.granted_by_pgt.granted_by_pt
        while prior_pt:
            proxies.append(prior_pt.service)
            prior_pt = prior_pt.granted_by_pgt.granted_by_pt

        if pgturl:
            logger.debug("Proxy-granting ticket request received for %s" %
                         pgturl)
            pgt = ProxyGrantingTicket.objects.create_ticket(service, pgturl, user=pt.user, granted_by_pt=pt)
        else:
            pgt = None
        return pt, pgt, proxies, None


def validate_proxy_granting_ticket(pgt, target_service):
    """
    Validate a proxy granting ticket string. Return an ordered pair
    containing a ``ProxyTicket``, or a ``ValidationError`` if ticket
    validation failed.
    """
    logger.debug("Proxy ticket request received for %s using %s" % (target_service, pgt))
    try:
        pgt = ProxyGrantingTicket.objects.validate_ticket(pgt, target_service)
    except ValidationError as e:
        logger.warning("%s %s" % (e.code, e))
        return None, e
    else:
        pt = ProxyTicket.objects.create_ticket(service=target_service, user=pgt.user, granted_by_pgt=pgt)
        return pt, None


def get_attributes(user, service):
    """
    Return a dictionary of user attributes from the set of configured
    callback functions.
    """
    attributes = {}

    callbacks = list(getattr(settings, 'MAMA_CAS_ATTRIBUTE_CALLBACKS', []))
    if callbacks:
        warnings.warn(
            'The MAMA_CAS_ATTRIBUTE_CALLBACKS setting is deprecated. Service callbacks '
            'should be configured using MAMA_CAS_VALID_SERVICES.', DeprecationWarning)
    callbacks.extend(get_config(service, 'CALLBACKS'))

    for path in callbacks:
        callback = import_string(path)
        attributes.update(callback(user, service))

    return attributes


def logout_user(request):
    """End a single sign-on session for the current user."""
    logger.debug("Logout request received for %s" % request.user)
    pprint("Logout request received for %s" % request.user)
    if request.user.is_authenticated():
        ServiceTicket.objects.consume_tickets(request.user)
        ProxyTicket.objects.consume_tickets(request.user)
        ProxyGrantingTicket.objects.consume_tickets(request.user)

        if getattr(settings, 'MAMA_CAS_ENABLE_SINGLE_SIGN_OUT', True):
            warnings.warn(
                'The MAMA_CAS_ENABLE_SINGLE_SIGN_OUT setting is deprecated. SLO '
                'should be configured using MAMA_CAS_VALID_SERVICES.', DeprecationWarning)
            ServiceTicket.objects.request_sign_out(request.user)

        logger.info("Single sign-on session ended for %s" % request.user)
        logout(request)
        messages.success(request, _('You have been successfully logged out'))
