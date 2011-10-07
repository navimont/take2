"""Take2 search REST Api

Supports searches for Contacts
Maintains a quick contact index table for simplified search and autocompletion
"""

import settings
import logging
import os
import calendar
from datetime import datetime, timedelta
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import memcache
from take2dbm import Contact, Person, Company, Take2, FuzzyDate, ContactIndex, PlainKey
from take2dbm import Email, Address, Mobile, Web, Other, Country
from take2access import get_login_user, get_current_user_template_values, MembershipRequired, visible_contacts
from take2index import lookup_contacts
from take2view import encode_contact

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
    # whose birthdays can I see?
    vcon = visible_contacts(login_user)
    # now find the ones with birthdays in the range
    for ckey in vcon:
        con = Contact.get(ckey)
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


def ask_geolocation(login_user):
    """function determines whether user shall be asked to submit positon or not

    Checks global setting and if global setting is True or not existent
    it will ask.
    If the user declined the request, it will not ask for the rest of the week.
    """

    if login_user.ask_geolocation:
        if login_user.ask_geolocation[0] == True:
            if len(login_user.ask_geolocation) > 1:
                # there may be restrictions regarding the time when I can ask again
                if login_user.ask_geolocation[1] > datetime.today():
                    return False

            return True
        else:
            return False
    else:
        # default is True
        login_user.ask_geolocation = [True]
        login_user.put()
        return True



class Take2Search(webapp.RequestHandler):
    """Run a search query over the current user's realm"""

    def get(self):
        login_user = get_login_user()
        template_values = get_current_user_template_values(login_user,self.request.uri)

        query = self.request.get('query',"")
        contact_key = self.request.get('key',"")
        archive = True if self.request.get('attic',"") == 'True' else False

        # ask user for geolocation
        template_values['geolocation_request'] = ask_geolocation(login_user)

        logging.debug("Search query: %s archive: %d key: %s " % (query,archive,contact_key))

        result = []

        #
        # last search button (home) was clicked
        #

        if login_user and self.request.get('last', False) == 'True':
            last = memcache.get('query', namespace=str(login_user.key()))
            if last:
                template_values['result_size'] = len(last['results'])
                template_values['query'] = last['query']
                for contact in db.get(last['results'][last['offset']:settings.RESULT_SIZE]):
                    con = encode_contact(contact, include_attic=False, login_user=login_user)
                    result.append(con)

        #
        # key is given
        #

        if contact_key:
            contact = Contact.get(contact_key)
            # this is basically a db dump
            con = encode_contact(contact, include_attic=False, login_user=login_user)
            result.append(con)

        #
        # query search
        #

        if query:
            cis = lookup_contacts(query)
            # Save the query result in memcache together with the information about
            # which portion of it we are displaying (the first result_size datasets as
            # it is a fresh query!)
            if login_user:
                if not memcache.set('query', {'query': query, 'offset': 0, 'results': cis}, time=5000, namespace=str(login_user.key())):
                    logging.error("memcache failed")
            template_values['result_size'] = len(cis)
            template_values['query'] = query
            for contact in db.get(cis[0:settings.RESULT_SIZE]):
                con = encode_contact(contact, include_attic=False, login_user=login_user)
                result.append(con)

        elif len(result) == 0:
            # display current user data
            if login_user and login_user.me:
                con = encode_contact(login_user.me, include_attic=False, login_user=login_user)
                result.append(con)

        #
        # birthday search
        #

        if login_user and login_user.me:
            # read from cache if possible
            template_values['birthdays'] = memcache.get('birthdays',namespace=str(login_user.key()))
            if not template_values['birthdays']:
                template_values['birthdays'] = upcoming_birthdays(login_user)
                # store in memcache
                memcache.set('birthdays',template_values['birthdays'],time=60*60*24,namespace=str(login_user.key()))

        # render search result page
        template_values['result'] = result
        path = os.path.join(os.path.dirname(__file__), 'take2search.html')
        self.response.out.write(template.render(path, template_values))



application = webapp.WSGIApplication([('/', Take2Search),
                                      ('/search.*', Take2Search),
                                      ],debug=settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

