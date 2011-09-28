"""Take2 import/export REST Api"""

import logging
import os
import yaml
import json
import settings
import datetime
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from take2dbm import Contact, Person, Company, Take2, FuzzyDate
from take2dbm import Link, Email, Address, Mobile, Web, Other, Country, PlainKey, ContactIndex
from take2access import get_current_user_template_values, visible_contacts, get_current_user_person

def encode_take2(contact, include_private_objects=False, include_attic=False):
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
        if obj.privacy == 0 and not include_private_objects:
            continue
        # do only enclose non-attic take2 properties unless attic parameter is set
        if obj.attic and not include_attic:
            continue
        res = {}
        res['key'] = str(obj.key())
        res['type'] = obj.class_name().lower()
        res['timestamp'] = obj.timestamp.isoformat()
        res['privacy'] = settings.PRIVACY[obj.privacy]
        res['attic'] = obj.attic
        if obj.class_name() == "Email":
            res['email'] = obj.email
        elif obj.class_name() == "Web":
            res['web'] = obj.web
        elif obj.class_name() == "Link":
            res['link'] = obj.link
            res['nickname'] = obj.nickname
            res['link_to'] = str(obj.link_to.key())
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


def encode_contact(contact, include_attic=False, signed_in=False, is_admin=False, me=None):
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

    if not (me or signed_in or is_admin):
        # the name is all which anonymous users will see
        return res

    if contact.class_name() == "Person":
        if contact.lastname:
            res['lastname'] = contact.lastname

    # In order to reveal more data, we must check if 'me' is allowed
    # to see it.
    visible = visible_contacts(me, include_attic)
    if not (contact.key() in visible or is_admin):
        return res

    if contact.class_name() == "Person":
        # google account
        if contact.user:
            user = {'nickname': contact.user.nickname(),
                    'email': contact.user.email(),
                    'user_id': contact.user.user_id(),
                    'federated_identity': contact.user.federated_identity(),
                    'federated_provider': contact.user.federated_provider()}
            res['user'] = user
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
    if contact.owned_by:
        res['owned_by'] = str(contact.owned_by.key())

    # takes care of the different take2 object structures
    if contact.owned_by == me or is_admin:
        include_private_objects=True
    else:
        include_private_objects=False
    res.update(encode_take2(contact, include_private_objects, include_attic))

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
            me = get_current_user_person(user)
            if key:
                con = Contact.get(key)
                if con:
                    contacts.append(encode_contact(con, include_attic=attic, signed_in=True, is_admin=True))
            else:
                # export everything this user can see
                for ckey in visible_contacts(me, include_attic=attic):
                    con = Contact.get(ckey)
                    contacts.append(encode_contact(con, include_attic=attic, me=me))

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

class Take2Import(webapp.RequestHandler):
    """Import data into database"""

    def post(self):
        user = users.get_current_user()
        template_values = get_current_user_template_values(user,self.request.uri)

        format = self.request.get("json", None)
        if not format:
            format = 'yaml'
        else:
            format = 'JSON'

        # not logged in
        if not user:
            self.redirect("/import")
            return

        # not an administrator
        if not users.is_current_user_admin():
            template_values["sorry"]  = "You have to be administrator to import data."
            path = os.path.join(os.path.dirname(__file__), 'take2sorry.html')
            self.response.out.write(template.render(path, template_values))
            return

        data = self.request.get("backup", None)

        # purge DB
        for c in Take2.all():
            c.delete()
        for c in Contact.all():
            c.delete()
        for c in Country.all():
            c.delete()
        for c in ContactIndex.all():
            c.delete()
        for c in PlainKey.all():
            c.delete()

        # list of countries
        for cd in settings.COUNTRIES:
            for cc,c in cd.items():
                country = Country(ccode=cc,country=c)
                country.put()

        if data:
            if format == 'JSON':
                dbdump = json.loads(data)
            else:
                dbdump = yaml.load(data)

        # dictionary will be filled with a reference to the freshly created person
        # object using the former key as stored in the dbdump. Neede later for resolving
        # the owned by references.
        old_key_to_new_key = {}
        new_contact_with_old_owned_by = []
        # list of contact objects
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
                if 'user' in contact:
                    entry.user = users.User(email=contact['user']['email'],
                                  federated_identity=contact['user']['federated_identity'])
            if contact['type'] == "company":
                entry = Company(name=contact['name'])
            if 'attic' in contact:
                entry.attic = contact['attic']
            if 'timestamp' in contact:
                dt,us= contact['timestamp'].split(".")
                entry.timestamp = datetime.datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S")
            if 'owned_by' in contact:
                new_contact_with_old_owned_by.append((entry,contact['owned_by']))
            else:
                # if the logged in user has a person entry:
                me = get_current_user_person(user)
                if me:
                    entry.owned_by = me
            # all data collected. store new entry
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
                        if classname == 'address':
                            obj = Address(adr=m['adr'], contact_ref=entry)
                            if 'location_lat' in m and 'location_lon' in m:
                                obj.location = db.GeoPt(lat=float(m['location_lat']),lon=float(m['location_lon']))
                            if 'landline_phone' in m:
                                obj.landline_phone = m['landline_phone']
                            if 'country' in m and m['country'] != "":
                                country = Country.all().filter("country =", country).get()
                                # If country name is not in DB it is added
                                if not country:
                                    country = Country(country=m['country'])
                                    country.put()
                                obj.country = country.key()
                        if obj:
                            # timestamp and privacy fields are the same for all take2 objects
                            if 'timestamp' in m:
                                dt,us= m['timestamp'].split(".")
                                obj.timestamp = datetime.datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S")
                            if 'privacy' in m:
                                for k,v in settings.PRIVACY.items():
                                    if v == m['privacy']:
                                        obj.privacy = k
                                        break
                            else:
                                obj.privacy = 1
                            if 'attic' in m:
                                obj.attic = m['attic']
                            obj.put()

        # Run over the contacts to resolve the owned_by references
        for contact,old_key in new_contact_with_old_owned_by:
            contact.owned_by = old_key_to_new_key[old_key]
            contact.put()

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

