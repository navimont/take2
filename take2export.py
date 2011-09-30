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

        data = self.request.get("backup", None)

        # purge DB
        logging.info("Delete DB entries for user %s" % (google_user.nickname()))
        contact_entries = 0
        take2_entries = 0
        login_user_entries = 0
        cindex_entries = 0
        for c in Contact.all().filter("owned_by =", login_user):
            # delete all dependent data
            for us in LoginUser.all().filter("me =", c):
                us.delete()
                login_user_entries = login_user_entries +1
            for ct in Take2.all().filter("contact_ref =", c):
                ct.delete()
                take2_entries = take2_entries + 1
            for ci in ContactIndex.all().filter("contact_ref =", c):
                ci.delete()
                cindex_entries = cindex_entries +1
            contact_entries = contact_entries + 1
            c.delete()
        logging.info("Deleted %d contacts, %d take2 %d contact index %d login user" % (contact_entries,take2_entries,cindex_entries,login_user_entries))

        if data:
            if format == 'JSON':
                dbdump = json.loads(data)
            else:
                dbdump = yaml.load(data)

        # dictionary will be filled with a reference to the freshly created person
        # key using the former key as stored in the dbdump. Neede later for resolving
        # the owned by references.
        old_key_to_new_key = {}
        contact_entries = 0
        take2_entries = 0
        for contact in dbdump:
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
            # all data collected. store new entry
            contact_entries = contact_entries + 1
            entry.put()
            # remember the key from the imported file for later dependency resolve
            if 'key' in contact:
                old_key_to_new_key[contact['key']] = entry.key()

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
                            obj = Address(adr=m['adr'], contact_ref=entry)
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
                            take2_entries = take2_entries + 1
                            obj.put()

            # generate search keys for new contact (only non-attic)
            check_and_store_key(entry)

        #
        # Resolve the link_to references
        #
        for link in Link.all():
            # This will retrieve the key without doing a get for the object.
            key = Link.link_to.get_value_for_datastore(link).id()
            link.link_to = old_key_to_new_key[key]
            link.put()

        logging.info("Added %d contacts and %d dependent datasets" % (contact_entries,take2_entries))

        self.redirect('/search')

application = webapp.WSGIApplication([('/importfile', Take2Import),
                                      ('/import', Take2SelectImportFile),
                                      ('/export.*', Take2Export),
                                     ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

