"""Take2 import/export REST Api"""

import logging
import os
import yaml
import json
import settings
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from take2dbm import Contact, Person, Company, Take2, FuzzyDate
from take2dbm import Link, Email, Address, Mobile, Web, Other, Country
from take2access import getCurrentUserTemplateValues

def encodeTake2(q_obj, attic=False):
    """Encodes the results of a query for Take2
    descendant objects.
    """
    results = []
    for obj in q_obj:
        res = {}
        res['key'] = str(obj.key())
        res['type'] = obj.class_name().lower()
        res['timestamp'] = obj.timestamp.isoformat()
        res['privacy'] = obj.privacy
        if obj.class_name() == "Email":
            res['email'] = obj.email
        elif obj.class_name() == "Web":
            res['web'] = obj.web
        elif obj.class_name() == "Link":
            res['link'] = obj.link
            res['nickname'] = obj.nickname
            res['link_to'] = str(obj.link_to.key())
        elif obj.class_name() == "Address":
            res['location_lat'] = obj.location.lat
            res['location_lon'] = obj.location.lon
            res['adr'] = obj.adr
            if obj.landline_phone:
                res['landline_phone'] = obj.landline_phone
            res['country'] = obj.country.country
            if obj.barrio:
                res['barrio'] = obj.barrio
            if obj.town:
                res['town'] = obj.town
        elif obj.class_name() == "Mobile":
            res['mobile'] = obj.mobile
        elif obj.class_name() == "Other":
            res['what'] = obj.what
            res['text'] = obj.text
        else:
            assert True, "Invalid class name: %s" % obj.class_name()
        results.append(res)
    return results


def encodeContact(contact, attic=False):
    """Encodes Contact data for export and returns a
    python data structure of dictionaries and lists.
    If attic=True, data will include the
    complete history and also archived data.
    """
    logging.debug("encode contact name: %s" % (contact.name))
    res = {}
    res['key'] = str(contact.key())
    res['name'] = contact.name
    res['type'] = contact.class_name().lower()
    if contact.owned_by:
        res['owned_by'] = str(contact.owned_by.key())
    else:
        # if no value is filled, it's owned by itself
        res['owned_by'] = str(contact.key())
    if contact.class_name() == "Person":
        # google account
        if contact.user:
            user = {'nickname': contact.user.nickname(),
                    'email': contact.user.email(),
                    'user_id': contact.user.user_id(),
                    'federated_identity': contact.user.federated_identity(),
                    'federated_provider': contact.user.federated_provider()}
            res['user'] = user
        if contact.lastname:
            res['lastname'] = contact.lastname
        if contact.birthday.has_year() or contact.birthday.has_month() or contact.birthday.has_day():
            res['birthday'] = "%04d-%02d-%02d" % (contact.birthday.year,contact.birthday.month,contact.birthday.day)
    elif contact.class_name() == "Company":
        # nothing to do
        pass
    else:
        assert True, "Invalid class name: %s" % contact.class_name()

    # now encode the contact's address, email etc.
    for take2 in [Email,Web,Address,Mobile,Link,Other]:
        q_obj = take2.all()
        q_obj.filter("contact =", contact.key())
        q_obj.order('-timestamp')
        # takes care of the different take2 object structures
        objs = encodeTake2(q_obj, attic)
        if objs:
            res[take2.class_name().lower()] = objs

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

        logging.info("export format:  attic: %d user: %s admin: %d" % (attic,user.nickname(),users.is_current_user_admin()))
        self.response.headers['Content-Type'] = 'text/plain'

        # Administrator exports everything
        contacts = []
        if users.is_current_user_admin():
            q_con = Contact.all()
            for con in q_con:
                contacts.append(encodeContact(con, attic))
        else:
            q_us = Contact.all()
            q_us.filter("user =", user)
            us = q_us.fetch(1)
            if len(us) != 1:
                logging.Critical("Found wrong # of user: %s [%s]" % (user.nickname(), ", ".join([u.name for u in us])))
                self.error(500)
                return
            contacts.append(encodeContact(us[0], False))

        if format == 'JSON':
            self.response.headers['Content-Type'] = "text/json"
            self.response.out.write(json.dumps(contacts,indent=2))
        else:
            self.response.headers['Content-Type'] = "text/yaml"
            self.response.out.write(yaml.dump(contacts,))

class Take2SelectImportFile(webapp.RequestHandler):
    """Present upload form for import file"""

    def get(self):
        user = users.get_current_user()
        template_values = getCurrentUserTemplateValues(user,self.request.uri)

        path = os.path.join(os.path.dirname(__file__), "take2import_file.html")
        self.response.out.write(template.render(path, template_values))


class Take2Import(webapp.RequestHandler):
    """Import data into database"""

    def post(self):
        user = users.get_current_user()
        format = self.request.get("json", None)
        if not format:
            format = 'yaml'
        else:
            format = 'JSON'

        # not logged in
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return

        template_values = {'nickname': user.nickname()}

        # not an administrator
        if not users.is_current_user_admin():
            path = os.path.join(os.path.dirname(__file__), 'sorrynoadmin.html')
            self.response.out.write(template.render(path, template_values))
            return

        # filename is given in URL
        file = self.request.get('file')
        if not file:
            logging.Error ("No 'file' in URL parameters")
            self.error(500)
            return

        data = self.request.get("backup", None)

        if data:
            if format == 'JSON':
                dbdump = json.loads(data)
            else:
                dbdump = yaml.load(data)



        self.redirect('/search')

def example():
    """Fill DB with some data for testing"""
    # purge DB
    for c in Contact.all():
        c.delete()
    for c in Country.all():
        c.delete()
    # list of countries
    for cd in settings.COUNTRIES:
        for cc,c in cd.items():
            country = Country(ccode=cc,country=c)
            country.put()
    # contacts
    eso = Company (name = 'ESO')
    eso.put()
    # Stephane with accent
    stef = Person(name = u'St\xe9phane',
                  lastname = 'Wehner',
                  birthday = FuzzyDate(year=0,month=6,day=15))
    stef.user = users.User("test@example.com")
    stef.put()
    email = Email(contact=stef,email='sw1@monton.de')
    email.put()
    dirk = Person(name='Dirk',owned_by=stef)
    dirk.put()
    link = Link(contact=stef,link="Friend",nickname="Pfitzi",link_to=dirk)
    link.put()
    libby = Person(name='Elizabeth')
    libby.user = users.User("libby@yahoo.com")
    libby.put()
    link = Link(contact=stef,link="Wife",nickname="Libby",link_to=libby)
    link.put()
    country = Country.all().filter("ccode =", "US").get()
    adr = Address(contact=stef,adr=['104 Adelphi','Brooklyn','NY','11205'],location=db.GeoPt(-70.1,30.0),country=country)
    adr.put()
    mobile = Mobile(contact=stef,mobile='616-204-7136')
    mobile.put()
    mobile = Mobile(contact=stef,mobile='616-920-2360')
    mobile.put()
    mobile = Mobile(contact=libby,mobile='616-204-7136')
    mobile.put()

application = webapp.WSGIApplication([('/importfile', Take2Import),
                                      ('/import', Take2SelectImportFile),
                                      ('/export.*', Take2Export),
                                     ],settings.DEBUG)

def main():
    example()
    logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

