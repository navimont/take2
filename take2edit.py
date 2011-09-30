"""Take2 edit REST Api"""

import settings
import logging
import os
import calendar
from datetime import datetime, timedelta
import yaml
from django.utils import simplejson as json
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from take2dbm import Contact, Person, Company, Take2, FuzzyDate
from take2dbm import Link, Email, Address, Mobile, Web, Other, Country
from take2export import encode_contact
from take2access import MembershipRequired, write_access, visible_contacts
from take2search import encode_contact_for_webpage
from take2geo import geocode_lookup

def save_take2_with_history(new,old):
    """Saves a new Take2 entity in the datastore. The new object
    replaces the old entity and we keep a history by leaving
    the old entity in the datastore but now pointing to the new one."""

    if new:
        new.put()
        if old:
            old.contact_ref = new
            old.put()

class ContactEdit(webapp.RequestHandler):
    """present a contact including old data (attic) for editing"""

    @MembershipRequired
    def get(self, user=None, me=None, template_values={}):
        contact_key = self.request.get("key", None)

        assert contact_key

        con = Contact.get(contact_key)

        # access rights check
        write_access(con,me)

        # call here geocoding for addresses which don't have filled the geo position
        q_adr = Address.all().filter("attic =", False).filter("contact_ref =", con)
        for adr in q_adr:
            if not adr.location:
                loc = geocode_lookup("%s, %s" % (", ".join(adr.adr),adr.country))
                if 'lat' in loc and 'lon' in loc:
                    adr.location = db.GeoPt(lat=float(loc['lat']),lon=float(loc['lon']))
                    adr.adr_zoom = loc['adr_zoom']
                    adr.put()

        contact = encode_contact(con, include_attic=True, me=me)
        # adjust fields and add extra fields for website renderer
        contact = encode_contact_for_webpage(contact, con, me)

        # render edit page
        template_values['contact'] = contact
        path = os.path.join(os.path.dirname(__file__), 'take2edit.html')
        self.response.out.write(template.render(path, template_values))


class PersonEdit(webapp.RequestHandler):
    """Edit existing person's data"""

    @MembershipRequired
    def get(self, user=None, me=None, template_values={}):
        person_key = self.request.get("key", "")

        # this is the person we edit
        person = Person.get(person_key)

        # access rights check
        write_access(person, me)

        template_values['link'] = None

        # define the html form fields for this object
        if me.key() == person.key():
            template_values['myself'] = True
        titlestr = "Edit Person data"
        template_values['name'] = "%s %s" % (person.name,person.lastname)
        template_values['firstname'] = person.name
        if person.lastname:
            template_values['lastname'] = person.lastname
        template_values['birthday'] = person.birthday
        # find relation to this person
        q_link = Link.all()
        q_link.filter("contact_ref =", me)
        q_link.filter("link_to =", person)
        link = q_link.fetch(1)
        if len(link):
            link = link[0]
            template_values['link'] = link.link
            template_values['nickname'] = link.nickname
        else:
            # person has no direct relation to me
            pass

        template_values['form_file'] = 'take2form_person.html'
        template_values['titlestr'] = titlestr
        template_values['instance'] = 'person'
        template_values['action'] = 'edit'
        template_values['key'] = person_key

        path = os.path.join(os.path.dirname(__file__), template_values['form_file'])
        self.response.out.write(template.render(path, template_values))


class PersonNew(webapp.RequestHandler):
    """Add a new personal contact"""

    @MembershipRequired
    def get(self, user=None, me=None, template_values={}):
        person_key = self.request.get("key", None)

        if person_key:
            # this is the person the new contact relates to (not necessarily the logged in user - me)
            person = Person.get(person_key)
        else:
            # new contact relates to me
            person_key = str(me.key())
            person = me

        template_values['link'] = None

        # all this stuff has to be in the form to have it ready if the
        # form has to be re-displayed after field error check (in PersonSave)
        template_values['form_file'] = 'take2form_person.html'
        template_values['titlestr'] = "New personal contact for %s %s" % (person.name, person.lastname)
        template_values['instance'] = 'person'
        template_values['action'] = 'new'
        template_values['key'] = person_key

        path = os.path.join(os.path.dirname(__file__), template_values['form_file'])
        self.response.out.write(template.render(path, template_values))


class PersonSave(webapp.RequestHandler):
    """Update/Save contact"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        contact_key = self.request.get("key", "")
        action = self.request.get("action", "")

        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            contact = Contact.get(contact_key)
            instance = contact.class_name().lower()
            myself = self.request.get("myself", False)
            # find the link between the edited person and myself (the one who is logged in)
            link = Link.all().filter("contact_ref =", me).filter("link_to =", contact).fetch(1)
            # access rights check
            write_access (contact, me)
        else:
            link = []

        #
        # update database
        #
        try:
            # allow the user to make input like 13/8
            bd = ("0%s/0/0" % self.request.get("birthday", "")).split("/")
            day = int(bd[0])
            month = int(bd[1])
            year = int(bd[2])
            if day < 0 or day > 31 or month < 0 or month > 12 or year < 0 or year > 9999:
                raise db.BadValueError('Illegal date')
            if action == 'new':
                person = Person(name=self.request.get("firstname", ""),
                                lastname=self.request.get("lastname", ""))
                person.birthday = FuzzyDate(day=day,month=month,year=year)
                person.owned_by = me
                person.put()
                contact = person
            else:
                person = contact
                person.name = self.request.get("firstname", "")
                person.lastname = lastname=self.request.get("lastname", "")
                person.birthday = FuzzyDate(day=day,month=month,year=year)
                person.put()
            # generate search keys for new contact
            check_and_store_key(person)
        except db.BadValueError as error:
            template_values['errors'] = [error]
        except ValueError as error:
            template_values['errors'] = [error]

        # update relation
        if len(link) > 0:
            link0 = link[0]
        else:
            link0 = None
        link_link = self.request.get("link", "")
        link_nickname = self.request.get("nickname", "")
        link1 = None
        if not link0 or (link0.link != link_link or link0.nickname != link_nickname):
            # Relation is new or was changed. Create new link
            link1 = Link(parent=link0, contact_ref=me,
                         nickname=link_nickname,
                         link=link_link,
                         link_to=contact)

        db.run_in_transaction(save_take2_with_history, new=link1, old=link0)

        # update visibility list
        visible_contacts(me, refresh=True)

        self.redirect('/editcontact?key=%s' % str(contact.key()))


class CompanyEdit(webapp.RequestHandler):
    """Edit existing company data"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        action,company_key = self.request.get("action", "").split("_")
        assert action in ['edit','attic','deattic'], "Undefined action: %s" % (action)

        company = Company.get(company_key)
        template_values['company_name'] = company.name

        if action != 'edit':
            if action == 'attic':
                company.attic = True
            else:
                company.attic = False
            company.put()
            self.redirect('/editcontact?key=%s' % str(company.key()))

        # define the html form fields for this object
        link = None
        if action == 'edit':
            titlestr = "Edit Institution data"
            template_values['name'] = company.name
            # find relation to this company
            q_link = Link.all()
            q_link.filter("contact_ref =", me)
            q_link.filter("link_to =", company)
            link = q_link.fetch(1)
            if len(link):
                link = link[0]
                template_values['link'] = link.link
        else:
            titlestr = "New Institution data"

        form_file = 'take2form_company.html'
        template_values['linklist'] = prepareListOfRelations(settings.INSTITUTION_RELATIONS,link)
        template_values['form_file'] = form_file
        template_values['titlestr'] = titlestr
        template_values['instance'] = 'company'
        template_values['action'] = action
        template_values['key'] = company_key

        path = os.path.join(os.path.dirname(__file__), form_file)
        self.response.out.write(template.render(path, template_values))


class CompanyNew(webapp.RequestHandler):
    """Edit existing company or add a new one"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        action,company_key = self.request.get("action", "").split("_")
        assert action in ['edit','attic','deattic'], "Undefined action: %s" % (action)

        # define the html form fields for this object
        link = None
        titlestr = "New Institution data"

        form_file = 'take2form_company.html'
        template_values['linklist'] = prepareListOfRelations(settings.INSTITUTION_RELATIONS,link)
        template_values['form_file'] = form_file
        template_values['titlestr'] = titlestr
        template_values['instance'] = 'company'
        template_values['action'] = action
        template_values['key'] = company_key

        path = os.path.join(os.path.dirname(__file__), form_file)
        self.response.out.write(template.render(path, template_values))

class CompanySave(webapp.RequestHandler):
    """Update/Save contact"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        company_key = self.request.get("key", "")
        action = self.request.get("action", "")

        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            company = Company.get(company_key)

        #
        # update database
        #
        try:
            if action == 'new':
                company = Company(name=self.request.get("company_name", ""))
                company.owned_by = me
                company.put()
            else:
                company = Company.get(company_key)
                company.name = name=self.request.get("company_name", "")
                company.put()
        except db.BadValueError as error:
            template_values['errors'] = [error]
        except ValueError as error:
            template_values['errors'] = [error]
        if 'errors' in template_values:
            template_values['linklist'] = prepareListOfRelations(settings.INSTITUTION_RELATIONS,link)
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), self.request.get("form_file"))
            self.response.out.write(template.render(path, template_values))
            return

        # update relation
        link = Link.all().filter("contact_ref =", me).filter("link_to =", company).fetch(1)
        if len(link) > 0:
            link0 = link[0]
        else:
            link0 = None
        link_link = self.request.get("linkselect")
        # currently not used for links to company
        link_nickname = self.request.get("nickname", "")
        link1 = None
        if not link0 or (link0.link != link_link or link0.nickname != link_nickname):
            # Relation is new or was changed. Create new link
            link1 = Link(parent=link0,
                         contact=me,
                         nickname=link_nickname,
                         link=link_link,
                         link_to=company)

        db.run_in_transaction(save_take2_with_history, new=link1, old=link0)

        self.redirect('/editcontact?key=%s' % str(company.key()))


class ContactAttic(webapp.RequestHandler):
    """Attic (archive) a contact"""

    @MembershipRequired
    def get(self, user=None, me=None, template_values={}):
        key = self.request.get("key", "")

        contact = Contact.get(key)
        assert contact, "Object key: %s is not a Contact" % key
        # access check
        assert write_access(contact, me)

        logging.debug("ContactAttic: %s key: %s" % (contact.name,key))

        contact.attic = True;
        contact.put();

        self.redirect('/editcontact?key=%s' % key)

class ContactDeattic(webapp.RequestHandler):
    """De-Attic (undelete) a contact"""

    @MembershipRequired
    def get(self, user=None, me=None, template_values={}):
        key = self.request.get("key", "")

        contact = Contact.get(key)
        assert contact, "Object key: %s is not a Contact" % (key)
        # access check
        assert contact.owned_by.key() == me.key(), "User %s cannot manipulate %s" % (str(t2.key()),str(contact.key()))

        logging.debug("ContactDeattic: %s key: %s" % (contact.name,key))

        contact.attic = False;
        contact.put();

        self.redirect('/editcontact?key=%s' % key)



def prepareListOfCountries(selected=None):
    """prepares a list of countries in a
    datastructure ready for the template use"""
    landlist = []
    for lc in Country.all():
        choice = {'country': lc.country}
        if lc.country == selected:
            choice['selected'] = "selected"
        landlist.append(choice)
    return landlist

class Take2Edit(webapp.RequestHandler):
    """Edit existing properties or add something new"""

    @MembershipRequired
    def get(self, user=None, me=None, template_values={}):
        action = self.request.get("action", "")
        instance = self.request.get("instance", "")
        key = self.request.get("key", "")
        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            t2 = Take2.get(key)
            # consistency checks on POSTed data
            assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
            contact = t2.contact_ref
        else:
            # if a new property is added, key contains the contact key
            contact = Contact.get(key)

        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))

        # access check
        assert write_access(contact, me)

        logging.debug("contact: %s action: %s instance: %s key: %s" %
                      (contact.name,action,instance,key))

        # title() capitalizes first letter
        titlestr = action.title()

        # define the html form fields for this take2 object
        form = []
        if instance == 'address':
            titlestr = titlestr+" address"
            form_file = 'take2form_address.html'
            if action == 'edit':
                template_values['landlist'] = prepareListOfCountries(t2.country.country)
                template_values['adr'] = "\n".join(t2.adr)
                if t2.location:
                    template_values['lat'] = t2.location.lat
                    template_values['lon'] = t2.location.lon
                template_values['landline_phone'] = "" if not t2.landline_phone else t2.landline_phone
                template_values['country'] = t2.country
                template_values['adr_zoom'] = ", ".join(t2.adr_zoom)
            else:
                template_values['landlist'] = prepareListOfCountries()
        if instance == 'mobile':
            titlestr = titlestr+" mobile phone"
            form_file = 'take2form_mobile.html'
            if action == 'edit':
                template_values['mobile'] = t2.mobile
        elif instance == 'web':
            titlestr = titlestr+" website"
            form_file = 'take2form_web.html'
            if action == 'edit':
                template_values['web'] = t2.web
            else:
                template_values['web'] = 'http://'
        elif instance == 'email':
            titlestr = titlestr+" email"
            form_file = 'take2form_email.html'
            if action == 'edit':
                template_values['email'] = t2.email
        elif instance == 'other':
            titlestr = titlestr+" misc. info"
            form_file = 'take2form_other.html'
            # prepare drop down menu with preselected relation
            taglist = []
            for tag in settings.OTHER_TAGS:
                choice = {'choice': tag}
                if action == 'edit' and tag == t2.what:
                    choice['selected'] = "selected"
                taglist.append(choice)
            template_values['taglist'] = taglist
            if action == 'edit':
                template_values['text'] = t2.text
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

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        instance = self.request.get("instance", "")
        key = self.request.get("key", "")
        action = self.request.get("action", "")

        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            t2 = Take2.get(key)
            # consistency checks on POSTed data
            assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
            contact = t2.contact_ref
        else:
            # if a new property is added, key contains the contact key
            contact = Contact.get(key)

        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))

        # access check
        assert write_access(contact, me)

        logging.debug("Take2Save; contact: %s instance: %s key: %s" % (contact.name,instance,key))

        #
        # update database
        #

        if action == 'edit':
            # load existing property
            obj0 = Take2.get(key)
        else:
            obj0 = None

        # Instantiate a fresh entity class if the action
        # is edit and some property has changed
        # OR if the action is new
        obj1 = None
        try:
            if instance == 'address':
                country = self.request.get("country", None)
                template_values['landlist'] = prepareListOfCountries(country)
                lat_raw = self.request.get("lat", "")
                lat = 0.0 if len(lat_raw) == 0 else float(lat_raw)
                lon_raw = self.request.get("lon", "")
                lon = 0.0 if len(lon_raw) == 0 else float(lon_raw)
                adr = self.request.get("adr", "").split("\n")
                adr_zoom = self.request.get("adr_zoom", "").split(",")
                # quite some effort in order to allow an empty phone number!
                phone = self.request.get("landline_phone", "").replace("None","")
                if len(phone):
                    landline_phone = db.PhoneNumber(phone)
                else:
                    landline_phone = None
                if not obj0 or not obj0.location or (obj0.location.lat != lat
                   or obj0.location.lon != lon
                   or obj0.adr != adr
                   or obj0.landline_phone != landline_phone
                   or obj0.country != country):
                    country_key = Country.all().filter("country =", country).get().key()
                    obj1 = Address(parent=obj0,
                                  location=db.GeoPt(lon=lon, lat=lat), adr=adr,
                                  landline_phone=landline_phone, country=country_key,
                                  adr_zoom=adr_zoom,
                                  contact_ref=contact.key())
            elif instance == 'mobile':
                mobile = db.PhoneNumber(self.request.get("mobile", ""))
                if not obj0 or obj0.mobile != mobile:
                    obj1 = Mobile(parent=obj0,mobile=mobile, contact_ref=contact.key())
            elif instance == 'web':
                web = db.Link(self.request.get("web", ""))
                if not obj0 or obj0.web != web:
                    obj1 = Web(parent=obj0, web=web, contact_ref=contact.key())
            elif instance == 'email':
                email = db.Email(self.request.get("email", ""))
                if not obj0 or obj0.email != email:
                    obj1 = Email(parent=obj0, email=email, contact_ref=contact.key())
            elif instance == 'other':
                what = self.request.get("what", "")
                text = self.request.get("text", "")
                if not obj0 or (obj0.what != what or obj0.text != text):
                    obj1 = Other(parent=obj0, what=what,text=text,contact_ref=contact.key())
            else:
                assert True, "Unhandled instance: %s" % (instance)
        except db.BadValueError as error:
            template_values['errors'] = [error]
        except ValueError as error:
            template_values['errors'] = [error]
        if 'errors' in template_values:
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), self.request.get("form_file"))
            self.response.out.write(template.render(path, template_values))
            return

        # new and old objects will be saved/updated
        db.run_in_transaction(save_take2_with_history, new=obj1,old=obj0)

        self.redirect('/editcontact?key=%s' % str(contact.key()))

class Take2Attic(webapp.RequestHandler):
    """Attic (archive) a property"""

    @MembershipRequired
    def get(self, user=None, me=None, template_values={}):
        instance = self.request.get("instance", "")
        key = self.request.get("key", "")

        t2 = Take2.get(key)
        # consistency checks
        assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
        contact = t2.contact_ref
        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))
        # access check
        assert write_access(contact, me)


        logging.debug("Attic: %s instance: %s key: %s" % (contact.name,instance,key))

        t2.attic = True;
        t2.put();

        self.redirect('/editcontact?key=%s' % str(contact.key()))

class Take2Deattic(webapp.RequestHandler):
    """Re-activate a property from archive"""

    @MembershipRequired
    def get(self, user=None, me=None, template_values={}):
        instance = self.request.get("instance", "")
        key = self.request.get("key", "")

        t2 = Take2.get(key)
        # consistency checks
        assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
        contact = t2.contact_ref
        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))
        # access check
        assert write_access(contact, me)

        logging.debug("De-attic: %s instance: %s key: %s" % (contact.name,instance,key))

        t2.attic = False;
        t2.put();

        self.redirect('/editcontact?key=%s' % str(contact.key()))

class Edittest(webapp.RequestHandler):
    """Re-activate a property from archive"""

    def get(self):
        path = os.path.join(os.path.dirname(__file__), 'take2search1.html')
        self.response.out.write(template.render(path, {}))


application = webapp.WSGIApplication([('/editcontact', ContactEdit),
                                      ('/newcompany', CompanyNew),
                                      ('/editcompany', CompanyEdit),
                                      ('/savecompany', CompanySave),
                                      ('/newperson', PersonNew),
                                      ('/editperson', PersonEdit),
                                      ('/saveperson', PersonSave),
                                      ('/atticcontact', ContactAttic),
                                      ('/deatticcontact', ContactDeattic),
                                      ('/edittest', Edittest),
                                      ('/edit.*', Take2Edit),
                                      ('/save.*', Take2Save),
                                      ('/attic.*', Take2Attic),
                                      ('/deattic.*', Take2Deattic),
                                     ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

