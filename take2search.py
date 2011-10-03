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
from google.appengine.api import taskqueue
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import memcache
from take2dbm import Contact, Person, Company, Take2, FuzzyDate, ContactIndex, PlainKey
from take2dbm import Email, Address, Mobile, Web, Other, Country
from take2access import get_login_user, get_current_user_template_values, MembershipRequired, visible_contacts
from take2index import lookup_contacts
from take2view import encode_contact


class Take2Search(webapp.RequestHandler):
    """Run a search query over the current user's realm"""

    def get(self):
        google_user = users.get_current_user()
        signed_in = True if google_user else False
        login_user = get_login_user(google_user)
        template_values = get_current_user_template_values(google_user,self.request.uri)

        # no connection between signed in user and any person in the database
        if login_user and not login_user.me:
            # prepare list of days and months
            daylist = ["(skip)"]
            daylist.extend(range(1,32))
            template_values['daylist'] = daylist
            monthlist=[(str(i),calendar.month_name[i]) for i in range(13)]
            monthlist[0] = ("0","(skip)")
            template_values['monthlist'] = monthlist
            path = os.path.join(os.path.dirname(__file__), 'take2welcome.html')
            self.response.out.write(template.render(path, template_values))
            return

        query = self.request.get('query',"")
        contact_key = self.request.get('key',"")
        if self.request.get('attic',"") == 'True':
            archive = True
        else:
            archive = False

        logging.debug("Search query: %s archive: %d key: %s " % (query,archive,contact_key))

        result = []

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

        elif query:
            cis = lookup_contacts(query, 100, first_call=True)
            # TODO implement various pages for long result lists
            template_values['query'] = query
            for contact in cis:
                con = encode_contact(contact, include_attic=False, login_user=login_user)
                result.append(con)
        else:
            # display current user data
            if login_user:
                con = encode_contact(login_user.me, include_attic=False, login_user=login_user)
                result.append(con)

        #
        # birthday search
        #

        if login_user:
            # read from cache if possible
            template_values['birthdays'] = memcache.get('birthdays',namespace=str(login_user.key()))
            if not template_values['birthdays']:
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
                template_values['birthdays'] = []
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
                        template_values['birthdays'].append(jubilee)
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

