"""Take2 search and edit REST Api"""

import settings
import logging
import os
import calendar
from datetime import datetime, timedelta
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
from take2export import encodeContact


def findCountryFromList(country):
    """Uses the country list to determine which country
    name is closest to the user's input
    """
    country = country.lower()
    countries = []
    for c in settings.COUNTRIES:
        c0 = c.values()[0]
        cl = c0.lower()
        if cl.find(country) >= 0:
            countries.append(c0)
    if len(countries) > 1:
        raise db.BadValueError, "Ambiguous input for country"
    if len(countries) < 1:
        raise db.BadValueError, "Missing input for country"

    return countries[0]

def encodeContactForWebpage(dump, contact):
    """Revises some field in the db dump (a strcuture of lists and dictionaries)
    so that the data can be used for the template renderer
    """
    # birthdays are displayed without the year of birth
    if 'birthday' in dump:
        dump['birthday'] = "%d %s" % (contact.birthday.day,
                                     calendar.month_name[contact.birthday.month])
    # to display relations we need to enrich the dump with
    # the relation's names
    if 'link' in dump:
        for link in dump['link']:
            rel = Contact.get(link['link_to'])
            link['name'] = rel.name

    return dump


class Take2Search(webapp.RequestHandler):
    """Run a search query over the current user's realm"""

    def get(self):
        user = users.get_current_user()

        query = self.request.get('query',"")
        contact_key = self.request.get('key',"")
        if self.request.get('attic',"") == 'True':
            archive = True
        else:
            archive = False

        logging.debug("Search query: %s archive: %d key: %s " % (query,archive,contact_key))

        template_values = {'nickname': user.nickname()}
        result = []

        #
        # key is given
        #

        if contact_key:
            contact = Contact.get(contact_key)
            # this is basically a db dump
            con = encodeContact(contact, attic=False)
            # adjust fields and add extra fields for website renderer
            con = encodeContactForWebpage(con, contact)
            result.append(con)


        #
        # query search
        #

        if query:
            q_res = []
            query1 = query+u"\ufffd"
            logging.debug("Search for %s >= name < %s" % (query,query1))
            q_con = Contact.all()
            q_con.filter("name >=", query).filter("name <", query1)
            q_res.extend(q_con)
            template_values['query'] = query

            for contact in q_res:
                con = encodeContact(contact, attic=False)
                # adjust fields and add extra fields for website renderer
                con = encodeContactForWebpage(con, contact)
                result.append(con)

        #
        # birthday search
        #
        daterange_from = datetime.today() - timedelta(days=5)
        daterange_to = datetime.today() + timedelta(days=14)
        # Convert to fuzzydate. Year is not important
        fuzzydate_from = FuzzyDate(day=daterange_from.day,
                                  month=daterange_from.month)
        fuzzydate_to = FuzzyDate(day=daterange_to.day,
                                  month=daterange_to.month)
        logging.debug("Birthday search from: %s to: %s" % (fuzzydate_from,fuzzydate_to))
        q_bd = Person.all()
        q_bd.filter("attic =", False)
        q_bd.filter("birthday >", fuzzydate_from)
        q_bd.filter("birthday <", fuzzydate_to)
        # TODO take care of December/January turnover
        template_values['birthdays'] = []
        # TODO: Fix later!
        if 0:
            for person in q_bd:
                # change birthday encoding from yyyy-mm-dd to dd Month
                person['birthday'] = "%d %s" % (person.birthday.day,
                                                person.month_name[person.birthday.month])
                template_values['birthdays'].append(person)

        # render administration page
        template_values['result'] = result
        path = os.path.join(os.path.dirname(__file__), 'take2search.html')
        self.response.out.write(template.render(path, template_values))


class ContactEdit(webapp.RequestHandler):
    """Edit existing person/contact or add a new one"""

    def post(self):
        user = users.get_current_user()

        if not user:
            self.redirect(users.create_login_url(self.request.uri))

        # find my own Person object
        q_me = Person.all()
        q_me.filter("user =", user)
        me = q_me.fetch(1)
        if len(me) < 1:
            template_values = {'sorry': "Your username is not in the database"}
            path = os.path.join(os.path.dirname(__file__), 'take2sorry.html')
            self.response.out.write(template.render(path, template_values))
            return
        else:
            me = me[0]

        action,instance,key = self.request.get("action", "").split("_")
        assert action in ['new','edit'], "Undefined action: %s" % (action)
        assert instance in ['person','contact'], "Undefined instance type: %s" % (instance)

        if action == 'edit':
            contact = Contact.get(key)

        # title() capitalizes first letter
        titlestr = action.title()

        template_values = {}
        # define the html form fields for this object
        form = []
        if action == 'edit':
            if contact.class_name() == "Person":
                template_values['name'] = "%s %s" % (contact.name,contact.lastname)
                template_values['firstname'] = contact.name
                template_values['lastname'] = contact.lastname
                template_values['birthday'] = contact.birthday
            else:
                template_values['name'] = contact.name
            # find relation to this person
            q_link = Link.all()
            q_link.filter("contact =", me)
            q_link.filter("link_to =", contact)
            link = q_link.fetch(1)[0]
            template_values['link'] = link.link
            template_values['nickname'] = link.nickname

        if contact.class_name() == "Person":
            template_values['linklist'] = settings.PERSON_RELATIONS
        else:
            template_values['linklist'] = settings.INSTITUTION_RELATIONS

        template_values['titlestr'] = titlestr
        template_values['action'] = action
        template_values['instance'] = instance
        template_values['key'] = key

        if contact.class_name() == 'Person':
            path = os.path.join(os.path.dirname(__file__), 'take2form_person.html')
        else:
            path = os.path.join(os.path.dirname(__file__), 'take2form_contact.html')
        self.response.out.write(template.render(path, template_values))


class ContactSave(webapp.RequestHandler):
    """Update/Save contact"""

    def post(self):
        user = users.get_current_user()

        if not user:
            self.redirect(users.create_login_url(self.request.uri))

        key = self.request.get("key", "")
        action = self.request.get("action", "")

        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            contact = Contact.get(key)

        #
        # update database
        #

        if contact.class_name() == 'Person':
            if action == 'new':
                person = Person(name=self.request.get("name", ""),
                                lastname=self.request.get("lastname", ""),
                                nickname=self.request.get("nickname", ""))
                day,month,year = self.request.get("birthday", "00/00/0000").split("/")
                person.birthday = FuzzyDate(day=int(day),month=int(month),year=int(year))
                person.put()
                contact = person
            else:
                person = contact
                person.name = self.request.get("name", "")
                person.lastname = lastname=self.request.get("lastname", "")
                person.nickname = nickname=self.request.get("nickname", "")
                day,month,year = self.request.get("birthday", "00/00/0000").split("/")
                person.birthday = FuzzyDate(day=int(day),month=int(month),year=int(year))
                person.put()
        else:
            if action == 'new':
                contact = Contact(name=self.request.get("name", ""))
                contact.put()
            else:
                contact = Contact.get(key)
                contact.name = name=self.request.get("name", "")
                contact.put()

        self.redirect('/search?key=%s' % str(contact.key()))


class Take2Edit(webapp.RequestHandler):
    """Edit existing properties or add something new"""

    def post(self):
        user = users.get_current_user()

        if not user:
            self.redirect(users.create_login_url(self.request.uri))

        action,instance,key = self.request.get("action", "").split("_")
        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            t2 = Take2.get(key)
            # consistency checks on POSTed data
            assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
            contact = t2.contact
        else:
            # if a new property is added, key contains the contact key
            contact = Contact.get(key)

        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))

        logging.debug("contact: %s action: %s instance: %s key: %s" %
                      (contact.name,action,instance,key))

        # title() capitalizes first letter
        titlestr = action.title()

        template_values = {}
        # define the html form fields for this take2 object
        form = []
        if instance == 'address':
            titlestr = titlestr+" address"
            form_file = 'take2form_address.html'
            if action == 'edit':
                template_values['adr'] = "\n".join(t2.adr)
                template_values['lat'] = t2.location.lat
                template_values['lon'] = t2.location.lon
                template_values['landline_phone'] = t2.landline_phone
                template_values['country'] = t2.country
        if instance == 'mobile':
            titlestr = titlestr+" mobile phone"
            form_file = 'take2form_mobile.html'
            if action == 'edit':
                template_values['mobile'] = t2.mobile
        elif instance == 'web':
            titlestr = titlestr+" website"
            if action == 'edit':
                form.append(["Web address", "web", t2.mobile])
            else:
                form.append(["Web address", "web", "http://"])
        elif instance == 'email':
            titlestr = titlestr+" email"
            form_file = 'take2form_email.html'
            if action == 'edit':
                template_values['email'] = t2.email
        elif instance == 'note':
            titlestr = titlestr+" note"
            if action == 'edit':
                form.append(["Note", "email", t2.email])
            else:
                form.append(["Note", "email"])
        else:
            assert True, "Unhandled take2 class: %s" % (take2_instance)

        template_values['titlestr'] = titlestr
        template_values['action'] = action
        if contact.class_name() == "Person":
            template_values['name'] = contact.name+" "+contact.lastname
        else:
            template_values['name'] = contact.name
        template_values['form'] = form
        template_values['instance'] = instance
        template_values['key'] = key
        template_values['form_file'] = form_file

        path = os.path.join(os.path.dirname(__file__), form_file)
        self.response.out.write(template.render(path, template_values))


class Take2Save(webapp.RequestHandler):
    """Save users/properties"""

    def post(self):
        user = users.get_current_user()

        if not user:
            self.redirect(users.create_login_url(self.request.uri))

        instance = self.request.get("instance", "")
        key = self.request.get("key", "")
        action = self.request.get("action", "")

        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            t2 = Take2.get(key)
            # consistency checks on POSTed data
            assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
            contact = t2.contact
        else:
            # if a new property is added, key contains the contact key
            contact = Contact.get(key)

        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))

        logging.debug("contact: %s instance: %s key: %s" %
                    (contact.name,instance,key))

        #
        # update database
        #

        if action == 'edit':
            # load existing property
            obj0 = Take2.get(key)

        # Instantiate a fresh entity class if the action
        # is edit and some property has changed
        # OR if the action is new
        obj1 = None
        try:
            if instance == 'address':
                lat = self.request.get("lat", "")
                lon = self.request.get("lon", "")
                adr = self.request.get("adr", "").split("\n")
                landline_phone = db.PhoneNumber(self.request.get("landline_phone", None))
                country = findCountryFromList(self.request.get("country", ""))
                if action == 'new' or (obj0.location.lat != lat
                   or obj0.location.lon != lon
                   or obj0.adr != adr
                   or obj0.landline_phone != landline_phone
                   or obj0.country != country):
                    obj1 = Address(location=db.GeoPt(lon=lon, lat=lat), adr=adr,
                                  landline_phone=landline_phone, country=country,
                                  contact=contact.key())
            elif instance == 'mobile':
                mobile = db.PhoneNumber(self.request.get("mobile", ""))
                if action == 'new' or obj0.mobile != mobile:
                    obj1 = Mobile(mobile=mobile, contact=contact.key())
            elif instance == 'web':
                web = db.Link(self.request.get("web", ""))
                if action == 'new' or obj0.web != web:
                    obj1 = Web(web=web, contact=contact.key())
            elif instance == 'email':
                email = db.Email(self.request.get("email", ""))
                if action == 'new' or obj0.email != email:
                    obj1 = Email(email=email, contact=contact.key())
            elif instance == 'note':
                note = db.Text(self.request.get("note", ""))
                if action == 'new' or obj0.note != note:
                    obj1 = Note(Note=note, contact=contact.key())
            elif instance == 'other':
                what = self.request.get("what", "")
                text = self.request.get("text", "")
                if action == 'new' or (obj0.what != what or obj0.text != text):
                    obj1 = Other(what=what,text=text,contact=contact.key())
            else:
                assert True, "Unhandled instance: %s" % (instance)
        except db.BadValueError as error:
            template_values = {'errors': [error]}
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), self.request.get("form_file"))
            self.response.out.write(template.render(path, template_values))
            return

        # a new object was created and will be saved
        if obj1:
            # TODO: in one transaction with the obj0 update
            obj1.put()
            if action == 'edit':
                # a new object is also created for edit, the
                # existing one stays in the storage but points
                # to the new object instead of the contact
                obj0.contact = obj1.key()
                obj0.put()

        self.redirect('/search?key=%s' % str(contact.key()))

application = webapp.WSGIApplication([('/search.*', Take2Search),
                                      ('/editcontact', ContactEdit),
                                      ('/savecontact', ContactSave),
                                      ('/editperson', ContactEdit),
                                      ('/saveperson', ContactSave),
                                      ('/edit.*', Take2Edit),
                                      ('/save', Take2Save),
                                     ],debug=True)

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

