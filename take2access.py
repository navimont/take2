"""Take2 functions for user access right checks"""

import os
import logging
from google.appengine.ext import db
from google.appengine.api import users
from take2dbm import Person

def getCurrentUserPerson(user):
    """Find the person which represents the currently logged in user"""
    q_me = Person.all()
    q_me.filter('user =', user)
    me = q_me.fetch(3)
    if len(me) > 0:
        if len(me) > 1:
            logging.Error ("more than one person with google account: %s [%s]" % (user.nickname,user.user_id))
        me = me[0]
    else:
        me = None

    return me


def getCurrentUserTemplateValues(user, page_uri, template_values=None):
    """Set up a set of template values
    Helpful for rendering the web page with some basic information about the user.
    """
    if not template_values:
        template_values = {}

    if user:
        template_values['loginout_url'] = users.create_logout_url(page_uri)
        template_values['loginout_text'] = 'logout %s' % (user.nickname())
    else:
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
                  'template_values': getCurrentUserTemplateValues(user, self.request.uri)}
        return target(self, **kwargs)

    # find my own Person object
    user = users.get_current_user()
    me = getCurrentUserPerson(user)
    if not me:
        return redirectToSignupPage
    else:
        logging.debug("returning wrapper")
        return wrapper

