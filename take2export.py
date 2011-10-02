"""Take2 import/export REST Api"""

import settings
import logging
import os
import yaml
from django.utils import simplejson as json
import datetime
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import taskqueue
from google.appengine.api import memcache
from take2dbm import Contact, Person, Company, Take2, FuzzyDate, LoginUser
from take2dbm import Link, Email, Address, Mobile, Web, Other, Country, PlainKey, ContactIndex
from take2access import get_current_user_template_values, visible_contacts, get_login_user
from take2contact_index import check_and_store_key

def encode_take2(contact, include_attic=False):
    """Encodes the contact's take2 property objects

    Returns a dictionary with the property's name
    as the key and a list of properties as values.
    """
    restypes = {}
    for take2 in [Email,Web,Address,Mobile,Link,Other]:
        restypes[take2.class_name().lower()] = []

    q_obj = Take2.all()
    q_obj.filter("contact_ref =", contact)
    q_obj.order('-timestamp')
    for obj in q_obj:
        # do only enclose non-attic take2 properties unless attic parameter is set
        if obj.attic and not include_attic:
            continue
        res = {}
        res['key'] = str(obj.key())
        res['type'] = obj.class_name().lower()
        res['timestamp'] = obj.timestamp.isoformat()
        res['attic'] = obj.attic
        if obj.class_name() == "Email":
            res['email'] = obj.email
        elif obj.class_name() == "Web":
            res['web'] = obj.web
        elif obj.class_name() == "Link":
            res['link'] = obj.link
            res['nickname'] = obj.nickname
            # avoid loading the actual linked object
            res['link_to'] = str(Link.link_to.get_value_for_datastore(obj))
        elif obj.class_name() == "Address":
            if obj.location:
                res['location_lat'] = obj.location.lat
                res['location_lon'] = obj.location.lon
            res['adr'] = obj.adr
            if obj.landline_phone:
                res['landline_phone'] = obj.landline_phone
            if obj.country:
                res['country'] = obj.country.country
            if obj.adr_zoom:
                res['adr_zoom'] = obj.adr_zoom
        elif obj.class_name() == "Mobile":
            res['mobile'] = obj.mobile
        elif obj.class_name() == "Other":
            res['what'] = obj.what
            res['text'] = obj.text
        else:
            assert True, "Invalid class name: %s" % obj.class_name()
        restypes[obj.class_name().lower()].append(res)

    return restypes


def encode_contact(contact, login_user, include_attic=False, is_admin=False):
    """Encodes Contact data for export and returns a python data structure of dictionaries and lists.

    The function takes into account the access rights and encodes only elements
    which the user is allowed to see.
    me is set to the user's own database entry (or None if not logged in or not in the DB)
    signed_in is set to True if the user is signed in
    If attic=True, data will include the complete history and also archived data.
    """
    logging.debug("encode contact name: %s" % (contact.name))
    res = {}
    # do only enclose non-attic contacts unless attic parameter is set
    if contact.attic and not include_attic:
        return {}
    res['name'] = contact.name

    if not login_user:
        # the name is all which anonymous users will see
        return res

    if contact.class_name() == "Person":
        if contact.lastname:
            res['lastname'] = contact.lastname

    # In order to reveal more data, we must check if 'me' is allowed
    # to see it.
    visible = visible_contacts(login_user, include_attic)
    if not (contact.key() in visible or is_admin):
        return res

    if contact.class_name() == "Person":
        if contact.birthday.has_year() or contact.birthday.has_month() or contact.birthday.has_day():
            res['birthday'] = "%04d-%02d-%02d" % (contact.birthday.year,contact.birthday.month,contact.birthday.day)
    elif contact.class_name() == "Company":
        # nothing to do
        pass
    else:
        assert True, "Invalid class name: %s" % contact.class_name()
    res['attic'] = contact.attic
    res['key'] = str(contact.key())
    res['type'] = contact.class_name().lower()
    res['timestamp'] = contact.timestamp.isoformat()
    # google account
    res['owned_by'] =  {'nickname': contact.owned_by.user.nickname(),
                    'email': contact.owned_by.user.email(),
                    'user_id': contact.owned_by.user.user_id(),
                    'federated_identity': contact.owned_by.user.federated_identity(),
                    'federated_provider': contact.owned_by.user.federated_provider()}

    # takes care of the different take2 object structures
    res.update(encode_take2(contact, include_attic))

    return res


class Take2Export(webapp.RequestHandler):
    """Export the relation between icons and osm tags (backup)"""

    def get(self):
        user = users.get_current_user()

        format = self.request.get("format", "JSON")

        if format not in ['JSON','yaml']:
            logging.Critical("Unknown format for export: %s" % (format))
            self.error(500)
            return

        # not logged in
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return

        if self.request.get('attic',"") == 'True':
            attic = True
        else:
            attic = False

        # shall a specific dataset be exported?
        key = self.request.get("key", None)


        logging.info("export format:  attic: %d user: %s admin: %d" % (attic,user.nickname(),users.is_current_user_admin()))
        self.response.headers['Content-Type'] = 'text/plain'

        # Administrator exports everything
        contacts = []
        if users.is_current_user_admin():
            if key:
                con = Contact.get(key)
                if con:
                    contacts.append(encode_contact(con, include_attic=attic, signed_in=True, is_admin=True))
            else:
                q_con = Contact.all()
                for con in q_con:
                    contacts.append(encode_contact(con, include_attic=attic, signed_in=True, is_admin=True))
        else:
            login_user = get_login_user(user)
            if key:
                con = Contact.get(key)
                if con:
                    contacts.append(encode_contact(con, include_attic=attic, signed_in=True, is_admin=True))
            else:
                # export everything this user can see
                for ckey in visible_contacts(login_user, include_attic=attic):
                    con = Contact.get(ckey)
                    contacts.append(encode_contact(con, include_attic=attic, me=login_user.me))

        self.response.headers['Content-Disposition'] = "attachment; filename=address_export.json"
        if format == 'JSON':
            self.response.headers['Content-Type'] = "text/plain"
            self.response.out.write(json.dumps(contacts,indent=2))
        else:
            self.response.headers['Content-Type'] = "text/yaml"
            self.response.out.write(yaml.dump(contacts,))

class Take2SelectImportFile(webapp.RequestHandler):
    """Present upload form for import file"""

    def get(self):
        user = users.get_current_user()
        template_values = get_current_user_template_values(user,self.request.uri)

        # not logged in
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return

        path = os.path.join(os.path.dirname(__file__), "take2import_file.html")
        self.response.out.write(template.render(path, template_values))

def  load_country_list():
    # list of countries
    for cd in settings.COUNTRIES:
        for cc,c in cd.items():
            country = Country(ccode=cc,country=c)
            country.put()

class Take2Import(webapp.RequestHandler):
    """Import data into database"""

    def post(self):
        google_user = users.get_current_user()
        template_values = get_current_user_template_values(google_user,self.request.uri)
        login_user = get_login_user(google_user)

        format = self.request.get("json", None)
        if not format:
            format = 'yaml'
        else:
            format = 'JSON'

        # not logged in
        if not google_user:
            self.redirect(users.create_login_url("/import"))
            return

        if memcache.get('import_status'):
            # there is already an import going on
            template_values['errors'] = ["Previous import is still processing. Please be patient..."]
            path = os.path.join(os.path.dirname(__file__), "take2import_file.html")
            self.response.out.write(template.render(path, template_values))
            return
        memcache.set('import_status', "Queued import task", time=30)
        memcache.set('import_data', self.request.get("backup"), time=300)

        logging.info("")

        # start background process
        taskqueue.add(url='/import_task', queue_name="import",
                      params={'login_user': str(login_user.key()), 'format': self.request.get("format", None)})

        # redirect to page which will show the import progress
        self.redirect('/import_status')

class Take2ImportStatus(webapp.RequestHandler):
    """Monitor import progress"""

    def get(self):
        """Function displays a simple page to monitor the import progress"""
        template_values = {}

        status = memcache.get('import_status')
        if status:
            template_values['import_status'] = status
        else:
            self.redirect('/')
            return

        path = os.path.join(os.path.dirname(__file__), "take2import_status.html")
        self.response.out.write(template.render(path, template_values))
        return

class Take2ImportTask(webapp.RequestHandler):
    """Used by task queue"""

    def post(self):
        """Function is called asynchronously to import data sets to the DB and
        delete existing data.
        """

        login_user = LoginUser.get(self.request.get("login_user", None))

        status = memcache.get('import_status')
        if not status:
            logging.critical("Failed to retrieve import status from memcache.")
            self.error(500)
            return

        data = memcache.get('import_data')
        if not data:
            logging.critical("Failed to retrieve import data from memcache.")
            self.error(500)
            return

        logging.info("Retrieved %d bytes for processing." % (len(data)) )
        memcache.set('import_status', "Parsing import data.", time=10)

        format=self.request.get("format", None)
        if format == 'JSON':
            dbdump = json.loads(data)
        else:
            dbdump = yaml.load(data)

        # purge DB
        logging.info("Import task starts deleting data...")
        contact_entries = db.Query(Contact,keys_only=True)
        contact_entries.filter("owned_by =", login_user)
        count = 0
        for c in contact_entries:
            # delete all dependent data
            q_t = db.Query(Take2,keys_only=True)
            q_t.filter("contact_ref =", c)
            db.delete(q_t)
            q_i = db.Query(ContactIndex,keys_only=True)
            q_i.filter("contact_ref =", c)
            db.delete(q_i)
            count = count +1
            memcache.set('import_status', "Deleting data: %d deleted." % (count), time=3)
        db.delete(contact_entries)
        logging.info("Import task deleted %d contact datasets" % (count))

        # dictionary will be filled with a reference to the freshly created person
        # key using the former key as stored in the dbdump. Needed later for resolving
        # the owned by references.
        old_key_to_new_key = {}
        take2_entries = []
        count = 0.0
        for contact in dbdump:
            memcache.set('import_status', "Importing data: %3.0f%% done." % ((count/len(dbdump))*100.0), time=3)
            logging.debug("Import type: %s name: %s id: %s attic: %s" % (contact['type'],
                           contact['name'] if 'name' in contact else '<no name>',
                           contact['id'] if 'id' in contact else '<no id>',
                           contact['attic'] if 'attic' in contact else '<no attic flag>'))
            if contact['type'] == "person":
                entry = Person(name=contact['name'])
                if 'lastname' in contact:
                    entry.lastname = lastname=contact['lastname']
                if 'birthday' in contact:
                    year,month,day = contact['birthday'].split('-')
                    entry.birthday = FuzzyDate(day=int(day),month=int(month),year=int(year))
            if contact['type'] == "company":
                entry = Company(name=contact['name'])
            # importer owns all the data
            entry.owned_by = login_user
            if 'attic' in contact:
                entry.attic = contact['attic']
            if 'timestamp' in contact:
                dt,us= contact['timestamp'].split(".")
                entry.timestamp = datetime.datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S")
            entry.put()
            # remember the key from the imported file for later dependency resolve
            if 'key' in contact:
                old_key_to_new_key[contact['key']] = entry.key()
            count = count+1

            # check for all take2 objects
            for take2 in [Email,Web,Address,Mobile,Link,Other]:
                classname = take2.class_name().lower()
                if classname in contact:
                    for m in contact[classname]:
                        obj = None
                        if classname == 'mobile':
                            obj = Mobile(mobile=m['mobile'], contact_ref=entry)
                        if classname == 'email':
                            obj = Email(email=m['email'], contact_ref=entry)
                        if classname == 'web':
                            if not m['web'].startswith("http://"):
                                m['web'] = 'http://'+m['web']
                            obj = Web(web=m['web'], contact_ref=entry)
                        if classname == 'other':
                            obj = Other(what=m['what'], text=m['text'], contact_ref=entry)
                        if classname == 'link':
                            # save the link_to key from the imported data in the link_to
                            # property for rater resolve
                            obj = Link(link_to=Key.from_path('Contact', m['link_to']), contact_ref=entry)
                            if 'nickname' in m:
                                obj.nickname = m['nickname']
                            link_to_references = (entry.key(),m['link_to'])
                        if classname == 'address':
                            obj = Address(adr=m['adr'], contact_ref=entry.key())
                            if 'location_lat' in m and 'location_lon' in m:
                                obj.location = db.GeoPt(lat=float(m['location_lat']),lon=float(m['location_lon']))
                            if 'landline_phone' in m:
                                obj.landline_phone = m['landline_phone']
                            if 'country' in m and m['country'] != "":
                                country = Country.all().filter("country =", m['country']).get()
                                # If country name is not in DB it is added
                                if not country:
                                    country = Country(country=m['country'])
                                    country.put()
                                obj.country = country.key()
                        if obj:
                            # common fields
                            if 'timestamp' in m:
                                dt,us= m['timestamp'].split(".")
                                obj.timestamp = datetime.datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S")
                            if 'attic' in m:
                                obj.attic = m['attic']
                            take2_entries.append(obj)

        memcache.set('import_status', "Store dependent entries.", time=30)

        #
        # Resolve the link_to references
        # and (if possible) the reference of the LoginUser to his/her own Person entry
        #
        login_user.me = None
        login_user.put()
        for t2 in take2_entries:
            if t2.class_name() == "Link":
                key = Link.link_to.get_value_for_datastore(t2).id()
                t2.link_to = old_key_to_new_key[key]
            if t2.class_name() == "Email":
                if t2.email == login_user.user.email():
                    login_user.me = t2.contact_ref
                    login_user.put()
                    logging.info("Resolved LoginUsers Person: %s using email: %s" % (t2.contact_ref.name, t2.email))

        #
        # Bulk store new entries
        #
        logging.info("Import task added %d contacts. Now store their %d dependent datasets" % (count,len(take2_entries)))
        db.put(take2_entries)
        logging.info("Import task done.")
        memcache.delete('import_status')

application = webapp.WSGIApplication([('/importfile', Take2Import),
                                      ('/import', Take2SelectImportFile),
                                      ('/import_status', Take2ImportStatus),
                                      ('/import_task', Take2ImportTask),
                                      ('/export.*', Take2Export),
                                     ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

