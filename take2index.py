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
from take2dbm import Contact, Person, Company, Take2, SearchIndex, Address

def plainify(string):
    """Removes all accents and special characters form string and converts
    string to lower case. If the string is made up of several words a list
    of these words is returned.

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


def update_index(obj, batch=False):
    """Updates obj-related keywords for the contact to which obj belongs

    If obj indices are already in the SearchIndex, their content is updated.
    If obj is new, it is added.

    Index keywords are:
    - name       (name: Contact)
    - nickname   (nickname: Person)
    - last name  (lastname: Person)
    - place      (adr_zoom: Address)
    """
    #
    # generate the keys and find the contact reference
    #
    new_keys = []
    contact_ref = None
    if obj.class_name() in ['Person','Contact','Company']:
        contact = obj
        new_keys = plainify(contact.name)
        if contact.class_name() == "Person":
            if contact.lastname:
                new_keys.extend(plainify(contact.lastname))
            if contact.nickname:
                new_keys.extend(plainify(contact.nickname))
    elif obj.class_name() in ['Address']:
        contact = obj.contact_ref
        # use the last two elements as search keys (should be town and neighborhood or similar)
        new_keys = plainify(" ".join(obj.adr_zoom[-2:]))
    else:
        logging.warning("update_index(): class %s is not considered here" % (obj.class_name()))

    logging.debug("Update %s with keys: %s" % (contact.name,new_keys))

    # read all index datasets with reference to obj
    data = SearchIndex.all().filter("data_ref =", obj).get()
    if data:
        # update existing dataset
        data.keys = new_keys
        data.attic = obj.attic or contact.attic
    elif new_keys:
        data = SearchIndex(keys=new_keys, attic=(obj.attic or contact.attic),
                            data_ref=obj, contact_ref=contact)
    else:
        # nothing to be indexed
        pass

    if batch:
        return data
    else:
        data.put()


class UpdateContactIndex(webapp.RequestHandler):
    """Used by task queue or cron job"""

    def get(self):
        """Function is called by cron to build a contact index DB table

        Call with a key to build index for this entity.
        """
        key = self.request.get("key", None)

        if key:
            con = Contact.get(Key(key))
            if con:
                update_index(con)
                return
            else:
                t2 = Take2.get(Key(key))
                if t2:
                    update_index(t2)
                    return
            logging.info("Could not find key: %s" % (key))
            return

        logging.info("Time to update contact index")

        # Update data in contact tables, latest first
        res = []
        for con in Contact.all():
            data = update_index(con, batch=True)
            if data:
                res.append(data)

        # bulk db operation
        db.put(res)
        logging.info("Contact index up to date: %d updated." % (len(res)))

        # Update data in contact tables, latest first
        res = []
        for adr in Address.all():
            data = update_index(adr, batch=True)
            if data:
                res.append(data)

        # bulk db operation
        db.put(res)
        logging.info("Town index up to date: %d updates." % (len(res)))


def lookup_contacts(term, include_attic=False):
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
        contacts = {}
        query0 = query
        query1 = query0+u"\ufffd"
        # look up plain query string in list of plain keys
        q_pk = db.Query(SearchIndex)
        q_pk.filter("keys >=", query0)
        q_pk.filter("keys <", query1)
        if not include_attic:
            q_pk.filter("attic =", False)
        for con_idx in q_pk:
            # insert contact index (not the object!) into a dictionary to avoid duplicates
            contacts[SearchIndex.contact_ref.get_value_for_datastore(con_idx)] = None
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
        # look up plain query string
        q_pk = db.Query(SearchIndex, keys_only=False)
        q_pk.filter("keys >=", query0)
        q_pk.filter("keys <", query1)
        q_pk.filter("attic =", False)
        # collect a max. of 16 distinct keys (or less if there aren't more)
        distinct_keys = {}
        for pk in q_pk:
            for key in pk.keys:
                if key >= query0 and key < query1:
                    distinct_keys[key] = key.capitalize()
            if len(distinct_keys) > 16:
                break
        if len(res0):
            res = [res0].append(distinct_keys.values())
        else:
            res = distinct_keys.values()

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

