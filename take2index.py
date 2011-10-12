"""Take2 buld quick search index to find a contact by its name, location, nickname etc.

    Stefan Wehner (2011)

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
from take2dbm import Contact, Person, Company, Take2, SearchIndex, Address, GeoIndex, LoginUser

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
    """Updates SearchIndex and GeoIndex tables with obj-related keywords
    and locations for the contact to which obj belongs.

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
    new_keys = None
    new_location = None
    contact_ref = None
    attic = False
    res = []
    try:
        obj_class = obj.class_name()
    except AttributeError:
        # for non poly model objects
        obj_class = obj.key().kind()
    if obj_class in ['Person','Contact','Company']:
        contact = obj
        new_keys = plainify(contact.name)
        if contact.class_name() == "Person":
            if contact.lastname:
                new_keys.extend(plainify(contact.lastname))
            if contact.nickname:
                new_keys.extend(plainify(contact.nickname))
        attic = obj.attic or contact.attic
    elif obj_class in ['Address']:
        try:
            contact = obj.contact_ref
        except db.ReferencePropertyResolveError:
            logging.warning("Address has invalid reference to contact %s" % (str(obj.key())))
            return None
        # use the elements as search keys (should be town and neighborhood or similar)
        new_keys = plainify(" ".join(obj.adr_zoom[:2]))
        if obj.location:
            new_location = obj.location
        attic = obj.attic or contact.attic
    elif obj_class in ['LoginUser']:
        try:
            contact = obj.me
        except db.ReferencePropertyResolveError:
            logging.warning("Address has invalid reference to contact %s" % (str(obj.key())))
            return None
        if obj.location:
            new_location = obj.location
    else:
        logging.debug("update_index(): class %s is not considered here" % (obj_class))
        return None

    if new_location:
        logging.debug("Update %s class %s with location: %f %f" % (contact.name,obj_class,new_location.lat,new_location.lon))
    if new_keys:
        logging.debug("Update %s class %s with keys: %s" % (contact.name,obj_class,new_keys))

    if new_keys:
        # read SearchIndex dataset with reference to obj
        data = SearchIndex.all().filter("data_ref =", obj).get()
        if data:
            # update existing dataset
            data.keys = new_keys
            data.attic = attic
        else:
            if batch:
                logging.warning("A new search index was created in batch for dataset: %d" % (obj.key().id()))
            data = SearchIndex(keys=new_keys, attic=attic,
                                data_ref=obj, contact_ref=contact)
        if batch:
            res.append(data)
        else:
            data.put()

    if new_location:
        # read GeoIndex dataset with reference to obj
        geo = GeoIndex.all().filter("data_ref =", obj).get()
        if geo:
            # update existing dataset
            geo.location = new_location
            geo.attic = attic
            # update geo reference field
            geo.update_location()
        else:
            if batch:
                logging.warning("A new geo index was created in batch for dataset: %d" % (obj.key().id()))
            geo = GeoIndex(location=new_location, attic=attic,
                           data_ref=obj, contact_ref=contact)
            geo.update_location()
        if batch:
            res.append(geo)
        else:
            geo.put()

    return res

class PurgeIndex(webapp.RequestHandler):
    """Used by administrator"""

    def get(self):
        if not users.is_current_user_admin():
            logging.critical("PurgeIndex called by non-admin")
            self.error(500)
            return

        logging.info("Purge index tables.")

        alldata = []
        for data in SearchIndex.all():
            alldata.append(data.key())
        db.delete(alldata)
        logging.info("%d datasets deleted in SearchIndex." % (len(alldata)))

        alldata = []
        for data in GeoIndex.all():
            alldata.append(data.key())
        db.delete(alldata)
        logging.info("%d datasets deleted in GeoIndex." % (len(alldata)))

        self.response.headers['Content-Type'] = "text/plain"
        self.response.out.write("/indexpurge done.")


class UpdateIndex(webapp.RequestHandler):
    """Used by admin or cron job"""

    def get(self):
        """Function is called by cron to build a contact index

        Call with a key to build index for this entity.
        """
        if not users.is_current_user_admin():
            logging.critical("UpdateIndex called by non-admin")
            self.error(500)
            return

        key = self.request.get("key", None)

        logging.info("Update index tables.")

        if key:
            con = Contact.get(Key(key))
            if con:
                update_index(con)
                # update dependant take2 entries
                for t2 in Take2.all().filter("contact_ref =", con):
                    update_index(t2)
                # update parent login_user
                user = LoginUser.all().filter("me =", con).get()
                if user:
                    update_index(user)
                return
            else:
                t2 = Take2.get(Key(key))
                if t2:
                    update_index(t2)
                    return
            logging.info("Could not find key: %s" % (key))
            return

        # Go through the tables which contribute to the index
        for table in [LoginUser,Contact,Address]:
            batch = []
            for obj in table.all():
                res = update_index(obj, batch=True)
                if res:
                    batch.extend(res)

            # bulk db operation
            db.put(batch)
            logging.info("%d updates." % (len(batch)))

        self.response.headers['Content-Type'] = "text/plain"
        self.response.out.write("/index done.")

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
        """Receives a query parameter and returns keywords that fit the query

        If the query consists of more than one word, the query string
        is split and only the last word in the query string is used to
        lookup matches.

        Example:
        'di' yields ['Dirk', 'Dieter', 'Diesbach']
        with more than one wordm the first  is simply returned in the result list
        'dieter h' yields ['dieter', 'Herbert', 'Hoheisel', 'Holdenbusch']
        """
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

class FixDb(webapp.RequestHandler):
    """Checks for currupt refeferences

    If fix=True it will delete the corrupted datasets
    """

    def get(self):
        if not users.is_current_user_admin():
            logging.critical("UpdateIndex called by non-admin")
            self.error(500)
            return

        fix = True if self.request.get("fix", "False") == "True" else False

        # look for LoginUser with invalid Person attached
        logging.info("Check LoginUser")
        err = False
        for obj in LoginUser.all():
            try:
                if not obj.me:
                    logging.critical("LoginUser %d has no Person attached" % ((obj.key().id())))
                    err = True
            except db.ReferencePropertyResolveError:
                logging.critical("LoginUser %d has invalid Person reference" % ((obj.key().id())))
                err = True
            if err:
                # check for dependent datasets
                count = Contact.all().filter("owned_by =", obj).count()
                logging.critical("LoginUser %d has %d dependant datasets" % (obj.key().id(),count))
                if fix:
                    obj.delete()
                    logging.info("%d deleted" % obj.key().id())
            err = False


        logging.info("Check Contact")
        err = False
        for obj in Contact.all():
            try:
                if not obj.owned_by:
                    logging.critical("Contact '%s' %d has no reference to owner" % (obj.name,obj.key().id()))
                    err = True
            except db.ReferencePropertyResolveError:
                logging.critical("Contact '%s' %d has invalid reference to owner" % (obj.name,obj.key().id()))
                count = LoginUser.all().filter("me =", obj).count()
                if count:
                    logging.critical("... but owner has reference!")
                err = True
            if err:
                # check for dependent datasets
                count = Take2.all().filter("contact_ref =", obj).count()
                logging.critical("Contact '%s' has %d dependent datasets" % (obj.name, count))
                if fix:
                    obj.delete()
                    logging.info("%d deleted" % obj.key().id())
            err = False

        logging.info("Check Take2")
        err = False
        for obj in Take2.all():
            try:
                if not obj.contact_ref:
                    logging.critical("Take2 has no reference to owner %s" % (obj.key().id()))
                    err = True
            except db.ReferencePropertyResolveError:
                logging.critical("Take2 has invalid reference to owner %s" % (obj.key().id()))
                err = True
            if err:
                if fix:
                    obj.delete()
                    logging.info("%d deleted" % obj.key().id())
            # location in address shall be set to default
            if obj.class_name() == 'Address' and not obj.location:
                logging.error("Address has null location %s. Fixed." % (obj.key().id()))
                obj.location=db.GeoPt(lon=0.0, lat=0.0)
                obj.put()
            err = False

        logging.info("Check SearchIndex")
        err = False
        for obj in SearchIndex.all():
            try:
                if not obj.contact_ref:
                    logging.critical("SearchIndex %d has no reference to owner" % (obj.key().id()))
                    err = True
            except db.ReferencePropertyResolveError:
                logging.critical("SearchIndex %d has invalid reference to owner" % (obj.key().id()))
                err = True
            if err:
                if fix:
                    obj.delete()
                    logging.info("%d deleted" % obj.key().id())
            err = False

        logging.info("Check GeoIndex")
        err = False
        for obj in GeoIndex.all():
            try:
                if not obj.contact_ref:
                    logging.critical("GeoIndex %d has no reference to owner" % (obj.key().id()))
                    err = True
            except db.ReferencePropertyResolveError:
                logging.critical("GeoIndex %d has invalid reference to owner" % (obj.key().id()))
                err = True
            if err:
                if fix:
                    obj.delete()
                    logging.info("%d deleted" % obj.key().id())
            err = False

        self.response.headers['Content-Type'] = "text/plain"
        self.response.out.write("/fix done.")



application = webapp.WSGIApplication([('/lookup', LookupNames),
                                      ('/index', UpdateIndex),
                                      ('/indexpurge', PurgeIndex),
                                      ('/fix', FixDb),
                                      ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

