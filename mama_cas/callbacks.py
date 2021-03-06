import logging
from pprint import pprint

logger = logging.getLogger(__name__)

def user_name_attributes(user, service):
    """Return all available user name related fields and methods."""
    attributes = {}
    attributes['username'] = user.get_username()
    attributes['full_name'] = user.get_full_name()
    attributes['short_name'] = user.get_short_name()
    return attributes


def user_model_attributes(user, service):
    """
    Return all fields on the user object that are not in the list
    of fields to ignore.
    """
    ignore_fields = ['id', 'password']
    attributes = {}
    for field in user._meta.fields:
        if field.name not in ignore_fields:
            attributes[field.name] = getattr(user, field.name)
    #pprint(attributes)
    logger.error("attributes:"+str(attributes))
    return attributes

def group_membership(user, service):
    #logger.error("groups:"+user.ldap_user.group_names)
    #groups = list(user.ldap_user.group_names)
    groups = user.groups.values_list('name', flat = True)
    logger.error("groups:"+str(groups))
    return {'groups': groups }
