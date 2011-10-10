"""Take2 functions for user access right checks"""

import os
import logging
import settings
import calendar
from google.appengine.ext import db
from google.appengine.api import users
from take2dbm import Person, Contact, LoginUser, FuzzyDate
from google.appengine.api import memcache
from google.appengine.api import users
from take2index import check_and_store_key
from take2beans import prepare_birthday_selectors

def write_access(obj, login_user):
    """Makes sure that me can edit the object

    Logs violations.
    Returns true if me has write access.
    """

    if not obj.class_name() in ['Person','Company']:
        if not obj.issubclass(Take2):
            logging.critical("Unknown object type: %s" % obj.class_name())
            return False
        contact = obj.contact_ref
    else:
        contact = obj

    logging.debug("contact.owned_by %s login_user %s" % (contact.owned_by.user.nickname(),login_user.user.nickname()))

    if contact.owned_by.key() != login_user.key():
        logging.critical("User %s %s cannot manipulate %s" % (login_user.user.nickname, login_user.user.user_id,str(obj.key())))
        return False

    return True

def get_login_user():
    """Find the account which represents the currently logged in google user"""

    authenticated_user = users.get_current_user()

    if not authenticated_user:
        return None

    q_me = LoginUser.all()
    q_me.filter('user_id =', authenticated_user.federated_identity())
    me = q_me.fetch(3)
    if len(me) > 0:
        if len(me) > 1:
            logging.critical ("more than one person with google account: %s [%s]" % (authenticated_user.nickname(),authenticated_user.user_id()))
        me = me[0]
    else:
        logging.error ("No Person registered for login_user")
        return None

    return me


def get_current_user_template_values(login_user, page_uri, template_values=None):
    """Set up a set of template values
    Helpful for rendering the web page with some basic information about the user.
    """
    if not template_values:
        template_values = {}

    if login_user:
        template_values['signed_in'] = True
        template_values['login_user_key'] = str(login_user.key())
        template_values['loginout_url'] = users.create_logout_url('/')
        if login_user.me:
            template_values['loginout_text'] = 'logout %s' % (login_user.me.name)
        else:
            template_values['loginout_text'] = 'logout'
    else:
        template_values['signed_in'] = False
        template_values['loginout_url'] = '/login'
        template_values['loginout_text'] = 'login'
    return template_values


def MembershipRequired(target):
    """Decorator: Is the currently logged in user (google account) also in the take2 DB?

    Also prepares the google user object, the user's take2 identity and some
    template_values and calls the target function with those as parameters.
    """
    def redirectToLoginPage(self):
        self.redirect('/login')
        return

    def wrapper (self):
        # find my own Person object
        login_user = get_login_user()
        if not login_user.me:
            return redirectToLoginPage
        else:
            # Add extra parameters
            kwargs = {'login_user': login_user,
                      'template_values': get_current_user_template_values(login_user, self.request.uri)}
            return target(self, **kwargs)

    return wrapper


def visible_contacts(login_user, include_attic=False, refresh=False):
    """Returns a set of keys of all contacts the user is allowed to see

    If refresh is set, the lookup is done again, otherwise a cached
    list may be returned.
    """

    if not login_user:
        return []

    # check in memcache
    if not refresh:
        visible = memcache.get('visible', namespace=str(login_user.key()))
        if visible:
            return visible

    visible = []
    logging.info("Updating access list for %s", login_user.user.nickname())

    #
    # 1. Can see all contacts which were created by the person
    #

    q_con = db.Query(Contact, keys_only=True)
    q_con.filter("owned_by =", login_user)
    if not include_attic:
        q_con.filter("attic =", False)
    for con in q_con:
        visible.append(con)

    visible = set(visible)
    if not memcache.set('visible', visible, time=5000,  namespace=str(login_user.key())):
        logging.error("memcache failed for key: %s" % str(login_user.key()))

    return visible

