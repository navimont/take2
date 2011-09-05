"""Take2 import/export REST Api"""

import logging
import os
import yaml
import json
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from take2dbm import Contact, Person, Company, Take2, FuzzyDate
from take2dbm import Link, Email, Address, Mobile, Web, Note, Other

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
        res['take2'] = obj.take2
        if obj.class_name() == "Email":
            res['email'] = obj.email
        elif obj.class_name() == "Web":
            res['web'] = obj.web
        elif obj.class_name() == "Link":
            res['link'] = obj.link
            res['link_to'] = str(obj.link_to.key())
        elif obj.class_name() == "Address":
            res['location_lat'] = obj.location.lat
            res['location_lon'] = obj.location.lon
            res['adr'] = obj.adr
            res['landline_phone'] = obj.landline_phone
            res['country'] = obj.country
        elif obj.class_name() == "Mobile":
            res['mobile'] = obj.mobile
        elif obj.class_name() == "Note":
            res['note'] = obj.note
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
    logging.debug("encode name: %s" % (contact.name))
    res = {}
    res['key'] = str(contact.key())
    res['name'] = contact.name
    res['type'] = contact.class_name().lower()
    if contact.class_name() == "Person":
        # google account
        res['user'] = contact.user
        # personal nickname
        res['nickname'] = contact.nickname
        res['lastname'] = contact.lastname
        res['birthday'] = "%04d-%02d-%02d" % (contact.birthday.year,contact.birthday.month,contact.birthday.day)
    elif contact.class_name() == "Company":
        # nothing to do
        pass
    else:
        assert True, "Invalid class name: %s" % contact.class_name()

    # now encode the contact's address, email etc.
    for take2 in [Email,Note,Web,Address,Mobile,Link,Other]:
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
            contacts.append(encodeContact(us, False))

        self.response.out.write(json.dumps(contacts,indent=2))
        self.response.out.write(yaml.dump(contacts,))


class Take2Import(webapp.RequestHandler):
    """Import data into database"""
    def get(self):
        user = users.get_current_user()

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

        try:
            fp = open(file,'r')
        except IOError:
            logging.Error ("Can't open backup file: %s" % (file))
            self.error(500)
            return

        icons = json.load(fp)
        for icon in icons:
            # open icon file
            try:
                iconfp = open(os.path.join(icondir,icon['file']),'r')
            except IOError:
                logging.Error ("Can't open icon file: %s/%s" % (icondir,file))
                continue

            # instantiate icon object
            epoicon = Epoicon(key=icon['key'], name=icon['name'], file=icon['file'], icon=iconfp.read())
            iconfp.close()
            epoicon.put()

        fp.close()
        self.redirect('/epoiadmin')

def example():
    for c in Contact.all():
        c.delete()
    eso = Company (name = 'ESO')
    eso.put()
    # Stephane with accent
    stef = Person(name = u'St\xe9phane',
                  nickname = 'Stef',
                  lastname = 'Wehner',
                  birthday = FuzzyDate(year=0,month=6,day=15))
    stef.put()
    email = Email(contact=stef,email='sw1@monton.de')
    email.put()
    dirk = Person(name='Dirk')
    dirk.put()
    link = Link(contact=stef,link="Friend",link_to=dirk)
    link.put()
    adr = Address(contact=stef,adr=['104 Adelphi','Brooklyn','NY','11205'],location=db.GeoPt(-70.1,30.0))
    adr.put()
    mobile = Mobile(contact=stef,mobile='616-204-7136')
    mobile.put()

application = webapp.WSGIApplication([('/import.*', Take2Import),
                                      ('/export', Take2Export),
                                     ],debug=True)

def main():
    example()
    logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
