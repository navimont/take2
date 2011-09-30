"""Take2 buld quick search index to find a contact by its name, location, nickname etc.

"""

import settings
import logging
import os
from django.utils import simplejson as json
import unicodedata
from random import shuffle
from datetime import datetime
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import memcache
from take2dbm import Contact, Person, Company, Take2, ContactIndex, PlainKey

def plainify(string):
    """Removes all accents and special characters form string and converts
    string to lower case

    Returns an array of plainified strings (splitted at space)
    """
    res = []
    for s1 in string.split(" "):
        s1 = s1.strip(",.;:\\?/!@#$%^&*()[]{}|\"'")
        s1 = unicode(s1)
        s1 = unicodedata.normalize('NFD',s1.lower())
        s1 = s1.replace("`", "")
        s1 = s1.encode('ascii','ignore')
        s1 = s1.replace("~", "")
        res.append(s1)

    return res


def check_and_store_key(contact):
    """Saves index keywords for the contact (name and last name)

    Returns number of additional keys saved in index
    """
    if contact.attic:
        return 0

    res = 0

    new_keys = (plainify(contact.name))
    if contact.class_name() == "Person":
        if contact.lastname:
            new_keys.extend(plainify(contact.lastname))

    for key in new_keys:
        # lookup plainified key
        pk = PlainKey.all().filter("plain_key =", key).get()
        if pk:
            if ContactIndex.all().filter("plain_key_ref =", pk).filter("contact_ref =", contact).get():
                break
        else:
            logging.debug("New plain key %s" % (key))
            pk = PlainKey(plain_key=key)
            res = res +1
            pk.put()
        # save
        ci = ContactIndex(plain_key_ref=pk, contact_ref=contact)
        ci.put()

    return 1

class UpdateContactIndex(webapp.RequestHandler):
    """Used by task queue"""

    def post(self):
        """Function is called asynchronously to build a contact index DB table

        Index contains:
        - Contact names
        - Person nicknames
        - Person lastnames
        - Contact locations
        """
        logging.info("Time to update contact index.")
        delete = []
        add = 0

        # check existing table for pointers to obsolete entries
        for ci in ContactIndex.all():
            if ci.contact_ref.attic:
                logging.debug("Delete obsolete contact index %s to %s" % (ci.plain_key_ref.plain_key, ci.contact_ref.name))
                delete.append(ci.key())
                delete.append(ci.plain_key_ref)
        # bulk delete
        db.delete(delete)

        last_refresh = memcache.get('contact_index_last_refresh')
        if not last_refresh:
            # we don't know when our last refresh was'
            last_refresh = datetime(1789,7,14)

        memcache.set('contact_index_last_refresh', datetime.now())

        # Update data in contact tables, latest first
        q_con = Contact.all()
        q_con.filter("attic =", False)
        q_con.order("-timestamp")
        for con in q_con:
            # only since last refresh
            if con.timestamp < last_refresh:
                break
            # keep track of total number
            add = add + check_and_store_key(con)

        logging.info("Contact index up to date: %d added. %d deleted." % (add,len(delete)))

def lookup_contacts(term, result_size=20, first_call=True):
    """Lookup function for search term.

    Returns Contact objects (Person or Company)
    Splits term if more than one word
    """

    # check in memcache
    if not first_call:
        contacts = memcache.get(term)
        # retrieve a chunk of result size
        res = contacts[0:result_size]
        # and put the rest back in storage
        if not memcache.set(term, contacts[result_size:], time=5000):
            logging.Error("memcache failed")
        return db.get(res)

    logging.debug(term)
    queries = plainify(term)
    logging.debug(queries)

    query_contacts = []
    for query in queries:
        plain_keys = []
        query0 = query
        query1 = query0+u"\ufffd"
        # look up plain query string in list of plain keys
        q_pk = db.Query(PlainKey, keys_only=True)
        q_pk.filter("plain_key >=", query0)
        q_pk.filter("plain_key <", query1)
        for key in q_pk:
            plain_keys.append(key)
        # retrieve contact keys for the plain keys
        contacts = {}
        for key in plain_keys:
            q_con = db.Query(ContactIndex)
            q_con.filter("plain_key_ref =", key)
            for con in q_con:
                contacts[ContactIndex.contact_ref.get_value_for_datastore(con)] = None
        # convert from map to set
        query_contacts.append(set(contacts.keys()))

    # At this point we have the result sets (contact keys) for the words in the query.
    # Now we need to find the contacts (hopefully very few) which are in _all_
    # of the contact sets
    contacts = query_contacts[0]
    for cons in query_contacts[1:]:
        contacts = contacts.intersection(cons)

    contacts = list(contacts)

    # retrieve first chunk of result size
    res = contacts[0:result_size]
    # and put the rest in storage
    if not memcache.set(term, contacts[result_size:], time=5000):
        logging.Error("memcache failed")
    return db.get(res)

class LookupNames(webapp.RequestHandler):
    """Quick lookup for search field autocompletion"""

    def get(self):
        """Receives a query parameter and returns keywords that fit the query"""
        user = users.get_current_user()
        signed_in = True if user else False

        res = []

        term = self.request.get('term',"")
        queries = plainify(term)

        res = []
        for query in queries:
            query0 = query
            query1 = query0+u"\ufffd"
            # look up plain query string in list of plain keys (keys only)
            q_pk = db.Query(PlainKey, keys_only=True)
            q_pk.filter("plain_key >=", query0)
            q_pk.filter("plain_key <", query1)
            keys = q_pk.fetch(12)
            if signed_in:
                contacts = []
                for key in keys:
                    contacts.extend(ContactIndex.all().filter("plain_key_ref =", key).fetch(12))
                # shuffle the list
                shuffle(contacts)
                # use only the first 21
                contacts = contacts[0:20]
                # replace ContactIndex by contact names
                for con in contacts:
                    if con.contact_ref.lastname:
                        res.append("%s %s" % (con.contact_ref.name, con.contact_ref.lastname))
                    else:
                        res.append(con.contact_ref.name)
            else:
                res = [key.plain_key.capitalize() for key in keys]

        # encode and return
        self.response.headers['Content-Type'] = "text/plain"
        self.response.out.write(json.dumps(res,indent=2))



application = webapp.WSGIApplication([('/lookup', LookupNames),
                                      ('/index', UpdateContactIndex),
                                      ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

