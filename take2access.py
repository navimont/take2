"""Take2 functions for user access right checks"""

import os
import logging
from google.appengine.ext import db
from google.appengine.api import users
from take2dbm import Person, Contact, Link
from google.appengine.api import memcache

def get_current_user_person(user):
    """Find the person which represents the currently logged in user"""
    if not user:
        return None

    q_me = Person.all()
    # q_me.filter('user =', users.User(user.email()))
    q_me.filter('user =', user)
    me = q_me.fetch(3)
    if len(me) > 0:
        if len(me) > 1:
            logging.error ("more than one person with google account: %s [%s]" % (user.nickname,user.user_id))
        me = me[0]
    else:
        logging.debug ("found none")
        me = None

    return me


def get_current_user_template_values(user, page_uri, template_values=None):
    """Set up a set of template values
    Helpful for rendering the web page with some basic information about the user.
    """
    if not template_values:
        template_values = {}

    if user:
        template_values['signed_in'] = True
        template_values['loginout_url'] = users.create_logout_url(page_uri)
        template_values['loginout_text'] = 'logout %s' % (user.nickname())
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
        template_values = {'sorry': "Your username is not in the database. Please sign up first."}
        path = os.path.join(os.path.dirname(__file__), 'take2sorry.html')
        self.response.out.write(template.render(path, template_values))
        return

    def wrapper (self):
        # Add extra parameters
        kwargs = {'user': user,
                  'me': me,
                  'template_values': get_current_user_template_values(user, self.request.uri)}
        return target(self, **kwargs)

    # find my own Person object
    user = users.get_current_user()
    me = get_current_user_person(user)
    if not me:
        return redirectToSignupPage
    else:
        logging.debug("returning wrapper")
        return wrapper


def visible_contacts(person, include_attic=False):
    """Returns a set of keys of all contacts the person is allowed to see"""

    if not person:
        return []

    # check in memcache
    visible = memcache.get(str(person.key))
    if visible:
        return visible

    #
    # 0. Include yourself
    #
    visible = [person.key()]

    #
    # 1. Can see all contacts which were created by the person
    #

    q_con = Contact.all().filter("owned_by =", person)
    if not include_attic:
        q_con.filter("attic =", False)
    for con in q_con:
        visible.append(con.key())

    #
    # 2. Can see all contacts person points to
    #

    q_ln = Link.all()
    if not include_attic:
        q_ln.filter("attic =", False)
    q_ln.filter("link_to =", person)
    q_ln.filter("privacy !=", "private")
    for con in q_ln:
        visible.append(con.key())

        #
        # 3. Can see all Contacts where contacts from 2) point to
        #

        q1_ln = Link.all()
        if not include_attic:
            q1_ln.filter("attic =", False)
        q1_ln.filter("link_to =", con)
        q1_ln.filter("privacy !=", "private")
        for con1 in q1_ln:
            visible.append(con.key())

    visible = set(visible)
    memcache.set(str(person.key), visible, time=500)

    return visible
