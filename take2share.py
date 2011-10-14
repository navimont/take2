"""Handles the pages which deal with sharing information

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
from google.appengine.api import memcache
from django.utils import simplejson as json
from take2dbm import SharedTake2, PublicTake2, RestrictedTake2
from take2view import encode_contact
from take2access import MembershipRequired, write_access

class Take2Share(webapp.RequestHandler):
    """Prepare the page which presents login_user's data for sharing"""

    @MembershipRequired
    def get(self, login_user=None, template_values={}):
        contact = encode_contact(login_user.me, login_user=login_user, include_attic=False, include_privacy=True)
        template_values['contact'] = contact

        # render search result page
        path = os.path.join(os.path.dirname(__file__), 'take2share.html')
        self.response.out.write(template.render(path, template_values))


class Take2ShareSave(webapp.RequestHandler):
    """Save the changes in privacy settings submitted from take2share page"""

    @MembershipRequired
    def post(self, login_user=None, template_values={}):
        transactions = self.request.get('transactions', None)
        if transactions:
            transaction_set = json.loads(transactions)
            contact_ref = transaction_set[0]
            # make sure we received data for the right user
            assert contact_ref == str(login_user.me.key()), "/sharesave received data for wrong user"

            # transfer all click transactions the user has made into a dictionary
            # with the key as dictionary key, so that only the last decision survives
            privacy_transactions = {}
            for tr in transaction_set[1:]:
                privacy_transactions[tr['key']] = tr['privacy']

            # apply privacy settings
            for key,privacy_setting in privacy_transactions.items():
                logging.debug("apply privacy setting contact: %s take2: %s %s" % (contact_ref,key,privacy_setting))
                # delete all existing datasets for this key
                delete = SharedTake2.all().filter("take2_ref =", Key(key))
                db.delete(delete)
                if privacy_setting == 'private':
                    pass
                elif privacy_setting == 'restricted':
                    RestrictedTake2(contact_ref=Key(contact_ref), take2_ref=Key(key)).put()
                elif privacy_setting == 'public':
                    data = PublicTake2(contact_ref=Key(contact_ref), take2_ref=Key(key)).put()
                else:
                    logging.critical("Unknown privacy setting: %s" % privacy_setting)
                    self.error(500)
                    return

        self.redirect("/editcontact?key=%s" % str(login_user.me.key()))


application = webapp.WSGIApplication([('/share', Take2Share),
                                      ('/sharesave', Take2ShareSave),
                                      ],debug=settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

