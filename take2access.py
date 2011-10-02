"""Take2 functions for user access right checks"""

import os
import logging
import settings
import calendar
from google.appengine.ext import db
from google.appengine.api import users
from take2dbm import Person, Contact, Link, LoginUser, FuzzyDate
from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from take2contact_index import check_and_store_key

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

    if contact.owned_by.key() != login_user.key():
        logging.critical("User %s %s cannot manipulate %s" % (login_user.user.nickname, login_user.user.user_id,str(obj.key())))
        return False

    return True

def get_login_user(google_user):
    """Find the account which represents the currently logged in google user"""

    if not google_user:
        return None

    q_me = LoginUser.all()
    q_me.filter('user =', google_user)
    me = q_me.fetch(3)
    if len(me) > 0:
        if len(me) > 1:
            logging.error ("more than one person with google account: %s [%s]" % (user.nickname,user.user_id))
        me = me[0]
    else:
        logging.info("Create new User for %s %s" % (google_user.nickname(), google_user.email()))
        me = LoginUser(user=google_user, location=db.GeoPt(0,0))
        me.put()

    return me


def get_current_user_template_values(google_user, page_uri, template_values=None):
    """Set up a set of template values
    Helpful for rendering the web page with some basic information about the user.
    """
    if not template_values:
        template_values = {}

    if google_user:
        template_values['signed_in'] = True
        template_values['loginout_url'] = users.create_logout_url(page_uri)
        template_values['loginout_text'] = 'logout %s' % (google_user.nickname())
    else:
        template_values['signed_in'] = False
        template_values['loginout_url'] = users.create_login_url(page_uri)
        template_values['loginout_text'] = 'login'
    return template_values


def MembershipRequired(target):
    """Decorator: Is the currently logged in user (google account) also in the take2 DB?

    Also prepares the google user object, the user's take2 identity and some
    template_values and calls the target function with those as parameters.
    """
    def redirectToSignupPage(self):
        path = os.path.join(os.path.dirname(__file__), 'take2welcome.html')
        self.response.out.write(template.render(path, []))
        return

    def redirectToLoginPage(self):
        self.redirect(users.create_login_url(self.request.uri))
        return

    def wrapper (self):
        # Add extra parameters
        kwargs = {'login_user': login_user,
                  'template_values': get_current_user_template_values(google_user, self.request.uri)}
        return target(self, **kwargs)

    # find my own Person object
    google_user = users.get_current_user()
    if not google_user:
        return redirect_to_login_page
    login_user = get_login_user(google_user)
    if not login_user.me:
        return redirectToSignupPage
    else:
        logging.debug("returning wrapper")
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
        visible = memcache.get(login_user.user.user_id())
        if visible:
            return visible

    visible = []
    logging.info("Updating access list for %s", login_user.user.nickname())

    #
    # 1. Can see all contacts which were created by the person
    #

    q_con = Contact.all().filter("owned_by =", login_user)
    if not include_attic:
        q_con.filter("attic =", False)
    for con in q_con:
        visible.append(con.key())

    visible = set(visible)
    logging.debug([Contact.get(key).name for key in visible])
    if not memcache.set(login_user.user.user_id(), visible, time=5000):
        logging.Error("memcache failed for key: %s" % login_user.user.user_id())

    return visible

class Take2Signup(webapp.RequestHandler):
    """User signup. Enter first name, last name and connect to a LoginUser (google) account"""

    def get(self):
        """processes the signup form"""
        google_user = users.get_current_user()
        login_user = get_login_user(google_user)
        template_values = get_current_user_template_values(google_user,self.request.uri)

        # not logged in
        if not google_user:
            self.redirect(users.create_login_url(self.request.uri))
            return

        # already connected
        if login_user.me:
            self.redirect('/search')
            return

        template_values['errors'] = []

        name=self.request.get("name", None)
        if not name:
            template_values['errors'].append("Your name is the only required field. Please fill it in.")
        terms=self.request.get("terms", None)
        if not terms:
            template_values['errors'].append("You must also acknowledge the terms and conditions.")

        if not template_values['errors']:
            person = Person(name=name, lastname=self.request.get("lastname", None))
            try:
                birthday = int(self.request.get("birthday", None))
            except ValueError:
                birthday = 0
            try:
                birthmonth = int(self.request.get("birthmonth", None))
            except ValueError:
                birthmonth = 0
            person.birthday = FuzzyDate(day=birthday,month=birthmonth,year=0000)
            person.owned_by = login_user
            person.put()
            # generate search keys for new contact
            check_and_store_key(person)
            # Connect to LoginUser
            login_user.me = person
            login_user.put()

        if len(template_values['errors']):
            # prepare list of days and months
            daylist = ["(skip)"]
            daylist.extend([str(day) for day in range(1,32)])
            template_values['daylist'] = daylist
            monthlist=[(str(i),calendar.month_name[i]) for i in range(13)]
            monthlist[0] = ("0","(skip)")
            template_values['monthlist'] = monthlist
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), "take2welcome.html")
            self.response.out.write(template.render(path, template_values))
            return

        self.redirect('/search')


application = webapp.WSGIApplication([('/signup', Take2Signup),
                                      ],debug=settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

