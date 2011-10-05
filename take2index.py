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
from take2dbm import Contact, Person, Company, Take2, ContactIndex, PlainKey, Address

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
        s1 = s1.strip()
        if len(s1):
            res.append(s1)

    return res


def check_and_store_key(obj, batch=False):
    """Updates index keywords for the contact

    Index keywords are:
    - name
    - lastname
    - nickname
    - town, neighborhood

    If an address or contact is deleted, the ContactIndex pointer from the
    keyword PlainKey to the entry is deleted (only the connection is deleted,
    both the plain key and the contact data remain in the database.)

    The batch parameter determines whether the data is added and deleted
    immediatley (batch=false) or returned so that the db operations can be
    executed bu the caller efficiently. If batch=True, it returns a dictionary
    with ContactIndex objects to be added and ContactIndex keys tp be deleted.
    """
    attic = False

    if obj.class_name() in ['Person','Contact','Company']:
        contact = obj
        new_keys = plainify(contact.name)
        if contact.class_name() == "Person":
            if contact.lastname:
                new_keys.extend(plainify(contact.lastname))
            if contact.nickname:
                new_keys.extend(plainify(contact.nickname))
        attic = contact.attic
    elif obj.class_name() in ['Address']:
        contact = obj.contact_ref
        # use the last two elements as search keys (should be town and neighborhood or similar)
        new_keys = plainify(" ".join(obj.adr_zoom[-2:]))
        attic = contact.attic or obj.attic
    else:
        assert False, "Class %s is not considered here" % (obj.class_name())

    add = []
    delete = []
    for key in new_keys:
        # lookup plainified key and store if not yet present
        pk = PlainKey.all().filter("plain_key =", key).get()
        if pk:
            ci = ContactIndex.all().filter("plain_key_ref =", pk).filter("contact_ref =", contact).get()
            if ci:
                if attic:
                    delete.append(ci)
                    logging.debug("%s -> %s delete" % (key,contact.name))
                else:
                    logging.debug("%s -> %s exists. ok." % (key,contact.name))
                    continue
        else:
            # store new plain key to database
            logging.debug("New plain key %s" % (key))
            pk = PlainKey(plain_key=key)
            pk.put()
        if not attic:
            # save the connection from key to contact
            logging.debug("%s -> %s added" % (key,contact.name))
            ci = ContactIndex(plain_key_ref=pk, contact_ref=contact)
            add.append(ci)

    if batch:
        return {'add': add, 'delete': delete}
    else:
        db.delete(delete)
        db.put(add)
        return {'add': len(add), 'delete': len(delete)}

class UpdateContactIndex(webapp.RequestHandler):
    """Used by task queue"""

    def get(self):
        """Function is called by cron to build a contact index DB table

        Index contains:
        - Contact names
        - Person nicknames
        - Person lastnames
        - Contact locations
        """
        refresh = self.request.get("refresh", "False") == "True"

        logging.info("Time to update contact index.")
        delete = []
        add = []
        last_refresh = memcache.get('contact_index_last_refresh')
        if not last_refresh:
            # we don't know when our last refresh was'
            last_refresh = datetime(1789,7,14)

        memcache.set('contact_index_last_refresh', datetime.now())

        # cleanup history entries
        if refresh:
            for t2 in Take2.all():
                key = Take2.contact_ref.get_value_for_datastore(t2)
                if key.kind() == 'Take2':
                    t2.delete()
                    logging.debug("Delete obsolete historic entry")

        # Update data in contact tables, latest first
        q_con = Contact.all()
        q_con.order("-timestamp")
        for con in q_con:
            if not refresh and (con.timestamp < last_refresh):
                break
            # add new ones only since last refresh
            # keep track of total number
            res = check_and_store_key(con, batch=True)
            add.extend(res['add'])
            delete.extend(res['delete'])

        # bulk db operation
        db.delete(delete)
        db.put(add)
        logging.info("Contact index up to date: %d added. %d deleted." % (len(add),len(delete)))

        delete = []
        add = []
        # Same update for address table
        q_adr = Address.all()
        q_adr.order("-timestamp")
        for adr in q_adr:
            if not refresh and (adr.timestamp < last_refresh):
                break
            # add new ones only since last refresh
            # keep track of total number
            res = check_and_store_key(adr, batch=True)
            add.extend(res['add'])
            delete.extend(res['delete'])

        # bulk db update
        db.delete(delete)
        db.put(add)
        logging.info("Town index up to date: %d added. %d deleted." % (len(add),len(delete)))


def lookup_contacts(term):
    """Lookup function for search term.

    Splits term if more than one word and looks for contacts which have _all_
    search terms in their relevant(indexed) fields. Indexed is name, nickname,
    lastname and town.
    Returns a list with Contact keys.
    """

    queries = plainify(term)
    logging.debug("lookup_contacts searches for %s" % " ".join(queries))

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

    return list(contacts)

class LookupNames(webapp.RequestHandler):
    """Quick lookup for search field autocompletion"""

    def get(self):
        """Receives a query parameter and returns keywords that fit the query"""
        term = self.request.get('term',"")
        queries = plainify(term)

        # if the query string is more than one term, lookup only the last
        res0 = " ".join(queries[0:-1])
        query0 = queries[-1]
        query1 = query0+u"\ufffd"
        # look up plain query string in list of plain keys (keys only)
        q_pk = db.Query(PlainKey, keys_only=False)
        q_pk.filter("plain_key >=", query0)
        q_pk.filter("plain_key <", query1)
        keys = q_pk.fetch(12)
        if len(res0):
            res = [res0]
        else:
            res = []
        for key in keys:
            res.append("%s %s" % (res0,key.plain_key.capitalize()))

        # encode and return
        self.response.headers['Content-Type'] = "text/plain"
        self.response.out.write(json.dumps(res))



application = webapp.WSGIApplication([('/lookup', LookupNames),
                                      ('/index', UpdateContactIndex),
                                      ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

