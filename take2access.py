"""Functions for user access right checks"""

import os
import logging
import settings
import calendar
from google.appengine.ext import db
from google.appengine.api import users
from take2dbm import Person, Contact, LoginUser, FuzzyDate
from google.appengine.api import memcache
from google.appengine.api import users
from take2beans import prepare_birthday_selectors
from datetime import datetime, timedelta

def upcoming_birthdays(login_user):
    """Returns a dictionary with names, nicknames and birthdays of the login_user's contacts"""

    res = []
    daterange_from = datetime.today() - timedelta(days=5)
    daterange_to = datetime.today() + timedelta(days=14)
    # Convert to fuzzydate and then to int (that's how it is stored in the db).
    # Year is least important
    fuzzydate_from = FuzzyDate(day=daterange_from.day,
                              month=daterange_from.month).to_int()
    fuzzydate_to = FuzzyDate(day=daterange_to.day,
                              month=daterange_to.month).to_int()
    if fuzzydate_from > fuzzydate_to:
        # end-of-year turnover
        fuzzydate_to_1 = 12310000
        fuzzydate_from_1 = 1010000
    else:
        fuzzydate_from_1 = fuzzydate_from
        fuzzydate_to_1 = fuzzydate_to
    logging.debug("Birthday search from: %d to %d OR  %d to %d" % (fuzzydate_from,fuzzydate_to_1,fuzzydate_from_1,fuzzydate_to))
    # now find the ones with birthdays in the range
    for con in Contact.all().filter("owned_by =", login_user):
        # skip companies
        if con.class_name() != "Person":
            continue
        if ((con.birthday.to_int() > fuzzydate_from and con.birthday.to_int() <= fuzzydate_to_1)
            or (con.birthday.to_int() > fuzzydate_from_1 and con.birthday.to_int() <= fuzzydate_to)):
            jubilee = {}
            # change birthday encoding from yyyy-mm-dd to dd Month
            jubilee['birthday'] = "%d %s" % (con.birthday.get_day(),
                                            calendar.month_name[con.birthday.get_month()])
            jubilee['name'] = con.name
            jubilee['nickname'] = con.nickname if con.nickname else ""
            res.append(jubilee)
    return res


def write_access(obj, login_user):
    """Makes sure that login_user can edit the object

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
    """Find the account which represents the currently logged in and authenticated user

    If user is not authenticated, returns None
    """

    authenticated_user = users.get_current_user()

    if not authenticated_user:
        return None

    q_me = LoginUser.all()
    q_me.filter('user =', authenticated_user)
    me = q_me.fetch(3)
    if len(me) > 0:
        if len(me) > 1:
            logging.critical ("more than one person with google account: %s [%s]" % (authenticated_user.nickname(),authenticated_user.user_id()))
        me = me[0]
    else:
        logging.warning ("No Person registered for login_user %s" % authenticated_user)
        logging.warning ("Trying email as user_id instead...")
        me = LoginUser.all().filter("user_id =", authenticated_user.email()).get()
        if not me:
            logging.warning ("Email not recognized either.")
            return None
        logging.warning ("Email worked.")

    # Check if login_user has a vaild person attached
    try:
        if me.me:
            logging.debug("Found login user person: %s" % (me.me.name))
    except db.ReferencePropertyResolveError:
        logging.critical ("Login user: %s has an invalid reference to Person" % (str(me.key())))
        return None

    return me


def get_current_user_template_values(login_user, page_uri, template_values=None):
    """Put together a set of template values regarding the logged in user.

    Needed for rendering the web page with some basic information about the user.
    """
    if not template_values:
        template_values = {}

    if not login_user:
        template_values['signed_in'] = False
        template_values['loginout_url'] = '/login'
        template_values['loginout_text'] = 'login'
        return template_values


    template_values['signed_in'] = True
    template_values['login_user_key'] = str(login_user.key())
    template_values['loginout_url'] = users.create_logout_url('/')
    try:
        template_values['loginout_text'] = 'logout %s' % (login_user.me.name)
    except db.ReferencePropertyResolveError:
        template_values['loginout_text'] = 'logout'
    #
    # remind us of birthdays!
    #

    # read from cache if possible
    template_values['birthdays'] = memcache.get('birthdays',namespace=str(login_user.key()))
    if not template_values['birthdays']:
        template_values['birthdays'] = upcoming_birthdays(login_user)
        # store in memcache
        memcache.set('birthdays',template_values['birthdays'],time=60*60*24,namespace=str(login_user.key()))

    #
    # initiate geolocation request on the user's machine
    #

    if login_user:
        # ask user for geolocation. The date check makes sure that we don't bother the user
        # with the request too often. Users who disable the geolocation feature have a
        # date a couple of years in the future.
        if not login_user.ask_geolocation or login_user.ask_geolocation < datetime.now():
            template_values['geolocation_request'] = True
            # set time for next request in the future. This setting becomes active if the
            # user declines the request in her browser. If she does cooperate,
            # take2geo will set the ask_geolocation to a time much closer to now
            login_user.ask_geolocation = datetime.now() + timedelta(hours=30)
            login_user.put()

    #
    # prepare current location information
    #

    yesterday = datetime.now() - timedelta(days=1)
    if login_user.location_timestamp > yesterday:
        template_values['login_user_place'] = login_user.place
        template_values['login_user_lat'] = login_user.location.lat
        template_values['login_user_lon'] = login_user.location.lon
    else:
        adr = memcache.get('location',namespace=str(login_user.key()))
        if not adr:
            # look up address
            q_adr = Address.all().filter("attic =", False).filter("contact_ref =", login_user.me)
            q_adr.order = "-timestamp"
            adr = q_adr.get()
            if adr:
                # store in memcache
                memcache.set('location',adr,time=60*60*24,namespace=str(login_user.key()))
        if adr:
            template_values['login_user_place'] = adr.adr_zoom[:2]
            template_values['login_user_lat'] = adr.location.lat
            template_values['login_user_lon'] = adr.location.lon
        else:
            # take NYC instead
            template_values['login_user_place'] = ""
            template_values['login_user_lat'] = 40.69
            template_values['login_user_lon'] = -73.07


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

