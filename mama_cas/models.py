from __future__ import unicode_literals

from datetime import timedelta
import logging
import os
import re
import time

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.crypto import get_random_string
from django.utils.encoding import python_2_unicode_compatible
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _

import requests

from mama_cas.compat import gevent
from mama_cas.exceptions import InvalidProxyCallback
from mama_cas.exceptions import InvalidRequest
from mama_cas.exceptions import InvalidService
from mama_cas.exceptions import InvalidTicket
from mama_cas.request import SingleSignOutRequest
from mama_cas.utils import add_query_params
from mama_cas.utils import is_scheme_https
from mama_cas.utils import clean_service_url
from mama_cas.utils import match_service
from mama_cas.utils import is_valid_service_url

if gevent:
    from gevent.pool import Pool
    from gevent import monkey
    monkey.patch_all(thread=False, select=False)


logger = logging.getLogger(__name__)


class TicketManager(models.Manager):
    def create_ticket(self, ticket=None, **kwargs):
        """
        Create a new ``Ticket``. Additional arguments are passed to the
        ``create()`` function. Return the newly created ``Ticket``.
        """
        if not ticket:
            ticket = self.create_ticket_str()
        if 'service' in kwargs:
            kwargs['service'] = clean_service_url(kwargs['service'])
        if 'expires' not in kwargs:
            expires = now() + timedelta(seconds=self.model.TICKET_EXPIRE)
            kwargs['expires'] = expires
        t = self.create(ticket=ticket, **kwargs)
        logger.debug("Created %s %s" % (t.name, t.ticket))
        return t

    def create_ticket_str(self, prefix=None):
        """
        Generate a sufficiently opaque ticket string to ensure the ticket is
        not guessable. If a prefix is provided, prepend it to the string.
        """
        if not prefix:
            prefix = self.model.TICKET_PREFIX
        return "%s-%d-%s" % (prefix, int(time.time()),
                             get_random_string(length=self.model.TICKET_RAND_LEN))

    def validate_ticket(self, ticket, service, renew=False, require_https=False):
        """
        Given a ticket string and service identifier, validate the
        corresponding ``Ticket``. If validation succeeds, return the
        ``Ticket``. If validation fails, raise an appropriate error.

        If ``renew`` is ``True``, ``ServiceTicket`` validation will
        only succeed if the ticket was issued from the presentation
        of the user's primary credentials.

        If ``require_https`` is ``True``, ``ServiceTicket`` validation
        will only succeed if the service URL scheme is HTTPS.
        """
        if not ticket:
            logger.error("No ticket string provided")
            raise InvalidRequest("No ticket string provided")

        if not self.model.TICKET_RE.match(ticket):
            logger.error("Ticket string %s is invalid" % ticket)
            raise InvalidTicket("Ticket string %s is invalid" % ticket)

        try:
            t = self.get(ticket=ticket)
        except self.model.DoesNotExist:
            logger.error("Ticket %s does not exist" % ticket)
            raise InvalidTicket("Ticket %s does not exist" % ticket)

        if t.is_consumed():
            logger.error("%s %s has already been used" %
                                (t.name, ticket))
            raise InvalidTicket("%s %s has already been used" %
                                (t.name, ticket))
        if t.is_expired():
            logger.error("%s %s has expired" % (t.name, ticket))
            raise InvalidTicket("%s %s has expired" % (t.name, ticket))

        if not service:
            logger.error("No service identifier provided")
            raise InvalidRequest("No service identifier provided")

        if require_https and not is_scheme_https(service):
            raise InvalidService("Service %s is not HTTPS" % service)

        if not is_valid_service_url(service):
            raise InvalidService("Service %s is not a valid %s URL" %
                                 (service, t.name))

        try:
            if not match_service(t.service, service):
                logger.error("%s %s for service %s is invalid for "
                        "service %s" % (t.name, ticket, t.service, service))
                raise InvalidService("%s %s for service %s is invalid for "
                        "service %s" % (t.name, ticket, t.service, service))
        except AttributeError:
            pass

        try:
            if renew and not t.is_primary():
                logger.error("%s %s was not issued via primary "
                                    "credentials" % (t.name, ticket))
                raise InvalidTicket("%s %s was not issued via primary "
                                    "credentials" % (t.name, ticket))
        except AttributeError:
            pass

        logger.debug("Validated %s %s" % (t.name, ticket))
        return t

    def delete_invalid_tickets(self):
        """
        Delete consumed or expired ``Ticket``s that are not referenced
        by other ``Ticket``s. Invalid tickets are no longer valid for
        authentication and can be safely deleted.

        A custom management command is provided that executes this method
        on all applicable models by running ``manage.py cleanupcas``.
        """
        for ticket in self.filter(Q(consumed__isnull=False) |
                                  Q(expires__lte=now())).order_by('-expires'):
            try:
                ticket.delete()
            except models.ProtectedError:
                pass

    def consume_tickets(self, user):
        """
        Consume all valid ``Ticket``s for a specified user. This is run
        when the user logs out to ensure all issued tickets are no longer
        valid for future authentication attempts.
        """
        for ticket in self.filter(user=user, consumed__isnull=True,
                                  expires__gt=now()):
            ticket.consume()


@python_2_unicode_compatible
class Ticket(models.Model):
    """
    ``Ticket`` is an abstract base class implementing common methods
    and fields for CAS tickets.
    """
    TICKET_EXPIRE = getattr(settings, 'MAMA_CAS_TICKET_EXPIRE', 90)
    TICKET_RAND_LEN = getattr(settings, 'MAMA_CAS_TICKET_RAND_LEN', 32)
    TICKET_RE = re.compile("^[A-Z]{2,3}-[0-9]{10,}-[a-zA-Z0-9]{%d}$" % TICKET_RAND_LEN)

    ticket = models.CharField(_('ticket'), max_length=255, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_('user'))
    expires = models.DateTimeField(_('expires'))
    consumed = models.DateTimeField(_('consumed'), null=True)

    objects = TicketManager()

    class Meta:
        abstract = True

    def __str__(self):
        return self.ticket

    @property
    def name(self):
        return self._meta.verbose_name

    def consume(self):
        """
        Consume a ``Ticket`` by populating the ``consumed`` field with
        the current datetime. A consumed ``Ticket`` is invalid for future
        authentication attempts.
        """
        self.consumed = now()
        self.save()

    def is_consumed(self):
        """
        Check a ``Ticket``s consumed state, consuming it in the process.
        """
        if self.consumed is None:
            self.consume()
            return False
        return True

    def is_expired(self):
        """
        Check a ``Ticket``s expired state. Return ``True`` if the ticket is
        expired, and ``False`` otherwise.
        """
        return self.expires <= now()


class ServiceTicketManager(TicketManager):
    def request_sign_out(self, user):
        """
        Send a single logout request to each service accessed by a
        specified user. This is called at logout when single logout
        is enabled.

        If gevent is installed, asynchronous requests will be sent.
        Otherwise, synchronous requests will be sent. Setting
        ``MAMA_CAS_ASYNC_CONCURRENCY`` limits concurrent requests for
        a logout event to the specified value.
        """
        def spawn(ticket, pool=None):
            if pool is not None:
                return pool.spawn(ticket.request_sign_out)
            return gevent.spawn(ticket.request_sign_out)

        tickets = list(self.filter(user=user, consumed__gte=user.last_login))

        if gevent:
            size = getattr(settings, 'MAMA_CAS_ASYNC_CONCURRENCY', 2)
            pool = Pool(size) if size else None
            sign_out_requests = [spawn(t, pool=pool) for t in tickets]
            gevent.joinall(sign_out_requests)
        else:
            for ticket in tickets:
                ticket.request_sign_out()


class ServiceTicket(Ticket):
    """
    (3.1) A ``ServiceTicket`` is used by the client as a credential to
    obtain access to a service. It is obtained upon a client's presentation
    of credentials and a service identifier to /login.
    """
    TICKET_PREFIX = 'ST'

    service = models.CharField(_('service'), max_length=255)
    primary = models.BooleanField(_('primary'), default=False)

    objects = ServiceTicketManager()

    class Meta:
        verbose_name = _('service ticket')
        verbose_name_plural = _('service tickets')

    def is_primary(self):
        """
        Check the credential origin for a ``ServiceTicket``. If the ticket was
        issued from the presentation of the user's primary credentials,
        return ``True``, otherwise return ``False``.
        """
        if self.primary:
            return True
        return False

    def request_sign_out(self):
        """
        Send a POST request to the ``ServiceTicket``s service URL to
        request sign-out. The remote session is identified by the
        service ticket string that instantiated the session.
        """
        request = SingleSignOutRequest(context={'ticket': self})
        try:
            modified_service = self.service.replace("http://","https://")
            resp = requests.post(modified_service, data={'logoutRequest': request.render_content()})
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.warning("Single sign-out request to %s returned %s" %
                           (self.service, e))
        else:
            logger.debug("Single sign-out request sent to %s" % self.service)


class ProxyTicket(Ticket):
    """
    (3.2) A ``ProxyTicket`` is used by a service as a credential to obtain
    access to a back-end service on behalf of a client. It is obtained upon
    a service's presentation of a ``ProxyGrantingTicket`` and a service
    identifier.
    """
    TICKET_PREFIX = 'PT'

    service = models.CharField(_('service'), max_length=255)
    granted_by_pgt = models.ForeignKey('ProxyGrantingTicket',
                                       verbose_name=_('granted by proxy-granting ticket'))

    class Meta:
        verbose_name = _('proxy ticket')
        verbose_name_plural = _('proxy tickets')


class ProxyGrantingTicketManager(TicketManager):
    def create_ticket(self, pgturl, **kwargs):
        """
        When a ``pgtUrl`` parameter is provided to ``/serviceValidate`` or
        ``/proxyValidate``, attempt to create a new ``ProxyGrantingTicket``.
        If PGT URL validation succeeds, create and return the
        ``ProxyGrantingTicket``. If validation fails, return ``None``.
        """
        pgtid = self.create_ticket_str()
        pgtiou = self.create_ticket_str(prefix=self.model.IOU_PREFIX)
        try:
            self.validate_callback(pgturl, pgtid, pgtiou)
        except InvalidProxyCallback as e:
            logger.warning("%s %s" % (e.code, e))
            return None
        else:
            # pgtUrl validation succeeded, so create a new PGT with the
            # previously generated ticket strings
            return super(ProxyGrantingTicketManager, self).create_ticket(ticket=pgtid,
                                                                         iou=pgtiou,
                                                                         **kwargs)

    def validate_callback(self, url, pgtid, pgtiou):
        """Verify the provided proxy callback URL."""
        if not is_scheme_https(url):
            raise InvalidProxyCallback("Proxy callback %s is not HTTPS" % url)

        if not is_valid_service_url(url):
            raise InvalidProxyCallback("%s is not a valid proxy callback URL" % url)

        # Check the proxy callback URL and SSL certificate
        url_params = add_query_params(url, {'pgtId': pgtid, 'pgtIou': pgtiou})
        verify = os.environ.get('REQUESTS_CA_BUNDLE', True)
        try:
            r = requests.get(url_params, verify=verify, timeout=3.0)
        except requests.exceptions.SSLError:
            msg = "SSL cert validation failed for proxy callback %s" % url
            raise InvalidProxyCallback(msg)
        except requests.exceptions.ConnectionError:
            msg = "Error connecting to proxy callback %s" % url
            raise InvalidProxyCallback(msg)
        except requests.exceptions.Timeout:
            msg = "Timeout connecting to proxy callback %s" % url
            raise InvalidProxyCallback(msg)

        # Check the returned HTTP status code
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            msg = "Proxy callback %s returned %s" % (url, e)
            raise InvalidProxyCallback(msg)


class ProxyGrantingTicket(Ticket):
    """
    (3.3) A ``ProxyGrantingTicket`` is used by a service to obtain proxy
    tickets for obtaining access to a back-end service on behalf of a
    client. It is obtained upon validation of a ``ServiceTicket`` or a
    ``ProxyTicket``.
    """
    TICKET_PREFIX = 'PGT'
    IOU_PREFIX = 'PGTIOU'
    TICKET_EXPIRE = getattr(settings, 'SESSION_COOKIE_AGE')

    iou = models.CharField(_('iou'), max_length=255, unique=True)
    granted_by_st = models.ForeignKey(ServiceTicket, null=True, blank=True,
                                      on_delete=models.PROTECT,
                                      verbose_name=_('granted by service ticket'))
    granted_by_pt = models.ForeignKey(ProxyTicket, null=True, blank=True,
                                      on_delete=models.PROTECT,
                                      verbose_name=_('granted by proxy ticket'))

    objects = ProxyGrantingTicketManager()

    class Meta:
        verbose_name = _('proxy-granting ticket')
        verbose_name_plural = _('proxy-granting tickets')

    def is_consumed(self):
        """Check a ``ProxyGrantingTicket``s consumed state."""
        return self.consumed is not None
