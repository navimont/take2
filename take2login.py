"""Take2 search REST Api

Supports searches for Contacts
Maintains a quick contact index table for simplified search and autocompletion
"""

import settings
import logging
import os
import calendar
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from take2dbm import LoginUser, Person, FuzzyDate
from take2access import get_login_user, get_current_user_template_values
from take2misc import prepare_birthday_selectors
from take2index import check_and_store_key


class Take2Welcome(webapp.RequestHandler):
    """Opens the page where the user can enter his/her name for the first time
       If the user is already known, it forwards to the main page"""

    def get(self):
        """processes the signup form"""
        google_user = users.get_current_user()
        login_user = LoginUser.all().filter('user =', google_user).get()
        template_values = get_current_user_template_values(login_user,self.request.uri)

        # not logged in
        if not google_user:
            self.redirect('/login')
            return

        # already connected
        if login_user and login_user.me:
            self.redirect('/')
            return

        # prepare list of days and months
        template_values.update(prepare_birthday_selectors())
        path = os.path.join(os.path.dirname(__file__), 'take2welcome.html')
        self.response.out.write(template.render(path, template_values))
        return


class Take2Signup(webapp.RequestHandler):
    """User signup. Checks for name, last name and connects to a LoginUser (google) account"""

    def get(self):
        """processes the signup form"""
        google_user = users.get_current_user()
        login_user = LoginUser.all().filter('user =', google_user).get()
        template_values = get_current_user_template_values(login_user,self.request.uri)

        # not logged in
        if not google_user:
            self.redirect('/login')
            return

        # already connected
        if login_user and login_user.me:
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
            except TypeError:
                birthday = 0
            try:
                birthmonth = int(self.request.get("birthmonth", None))
            except ValueError:
                birthmonth = 0
            except TypeError:
                birthmonth = 0
            person.birthday = FuzzyDate(day=birthday,month=birthmonth,year=0000)
            person.owned_by = login_user
            person.put()
            # generate search keys for new contact
            check_and_store_key(person)
            # Create login_user in DB
            login_user = LoginUser(user=google_user, me=person, location=db.GeoPt(0,0))
            login_user.put()

        if len(template_values['errors']):
            template_values.update(prepare_birthday_selectors())
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), "take2welcome.html")
            self.response.out.write(template.render(path, template_values))
            return

        self.redirect('/search')

class OpenIdLogin(webapp.RequestHandler):
    """creates the openid login url and redirects the browser"""

    def get(self):
        openid_url = self.request.GET.get('openid_identifier')
        if not openid_url:
            self.redirect('/_ah/login_required')
        else:
            self.redirect(users.create_login_url(dest_url='/welcome', federated_identity=openid_url))


class Take2Login(webapp.RequestHandler):
    """Login page

    Anonymous: Present login page
    Logged in users who use weschnitz for the first time: they need to enter their data
    Logged in users who are known users: go to main page
    """

    def get(self):
        login_user = get_login_user()
        template_values = get_current_user_template_values(login_user,self.request.uri)

        # not logged in. display login options
        if not login_user:
            path = os.path.join(os.path.dirname(__file__), 'take2login.html')
            self.response.out.write(template.render(path, template_values))
            return

        if not login_user.me:
            self.redirect('/welcome')
            return

        self.redirect('/')
        return

# PAGE FLOW:
# /_ah/login_required or
# /login              presents the openId logos to choose from
# /openid_login       takes the chosen provider (parameter ) and forwards there for the login
# /welcome            opens the page where the user can enter his/her name for the first time
#                     If the user is already known, it forwards to the main page
# /signup             Checks the parameter entered on the welcome page and stores them, if ok
#                     Otherwise the site is repeated for correction

application = webapp.WSGIApplication([('/welcome', Take2Welcome),
                                      ('/openid_login', OpenIdLogin),
                                      ('/login', Take2Login),
                                      ('/_ah/login_required', Take2Login),
                                      ('/signup', Take2Signup),
                                      ],debug=settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

