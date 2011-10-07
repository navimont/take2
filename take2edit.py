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
from take2dbm import Email, Address, Mobile, Web, Other, Country, OtherTag
from take2access import MembershipRequired, write_access, visible_contacts
from take2view import encode_contact
from take2geo import geocode_lookup
from take2index import check_and_store_key
from take2misc import prepare_birthday_selectors

class ContactEdit(webapp.RequestHandler):
    """present a contact including old data (attic) for editing"""

    @MembershipRequired
    def get(self, login_user=None, template_values={}):
        contact_key = self.request.get("key", None)

        assert contact_key

        con = Contact.get(contact_key)

        # access rights check
        if not write_access(con,login_user):
            self.error(500)
            return

        contact = encode_contact(con, login_user, include_attic=True)

        # render edit page
        template_values['contact'] = contact
        path = os.path.join(os.path.dirname(__file__), 'take2edit.html')
        self.response.out.write(template.render(path, template_values))



class PersonSave(webapp.RequestHandler):
    """Update/Save contact"""

    @MembershipRequired
    def post(self, login_user=None, template_values={}):
        person_key = self.request.get("key", "")
        action = self.request.get("action", "")

        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            person = Contact.get(person_key)
            instance = person.class_name().lower()
            # access rights check
            if not write_access (person, login_user):
                self.error(500)
                return
        else:
            person = None

        #
        # update database
        #
        try:
            if action == 'new':
                person = Person(name=self.request.get("firstname", ""),
                                lastname=self.request.get("lastname", ""))
                person.owned_by = login_user
            else:
                person.name = self.request.get("firstname", "")
                person.lastname = lastname=self.request.get("lastname", "")
            try:
                birthday = int(self.request.get("birthday", None))
            except ValueError:
                birthday = 0
            except TypeError:
                birthday = 0
            try:
                birthmonth = int(self.request.get("birthmonth", None))
            except ValueError:
                birthmonth = 0
            except TypeError:
                birthmonth = 0
            try:
                birthyear = int(self.request.get("birthyear", None))
            except ValueError:
                birthyear = 0
            except TypeError:
                birthyear = 0
            person.birthday = FuzzyDate(day=birthday,month=birthmonth,year=birthyear)
            back_ref = self.request.get("back_ref", None)
            if back_ref:
                person.back_ref = Key(back_ref)
                person.back_rel = self.request.get("back_rel", "")
            person.put()
            # generate search keys for new contact
            check_and_store_key(person)
        except db.BadValueError:
            template_values['errors'] = ["Invalid data"]
        except ValueError:
            template_values['errors'] = ["Value error"]
        if 'errors' in template_values:
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), self.request.get("form_file"))
            self.response.out.write(template.render(path, template_values))
            return

        # update visibility list
        visible_contacts(login_user, refresh=True)

        self.redirect('/editcontact?key=%s' % str(person.key()))


class CompanyNew(webapp.RequestHandler):
    """Edit existing company or add a new one"""

    @MembershipRequired
    def post(self, login_user=None, template_values={}):
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
    def post(self, login_user=None, template_values={}):
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
        except db.BadValueError:
            template_values['errors'] = ["BadValueError"]
        except ValueError:
            template_values['errors'] = ["ValueError"]
        if 'errors' in template_values:
            template_values['linklist'] = prepareListOfRelations(settings.INSTITUTION_RELATIONS,link)
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), self.request.get("form_file"))
            self.response.out.write(template.render(path, template_values))
            return

        # update visibility list
        visible_contacts(login_user, refresh=True)

        self.redirect('/editcontact?key=%s' % str(company.key()))

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

def prepareListOfOtherTags():
    """prepares a list of previously used tags in a  data structure ready for the template use"""
    taglist = []
    for tag in OtherTag.all():
        taglist.append(tag.tag)
    return taglist

class Take2Save(webapp.RequestHandler):
    """Save users/properties"""

    @MembershipRequired
    def post(self, login_user=None, template_values={}):
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
        if not write_access(contact, login_user):
            self.error(500)
            return

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
        try:
            if instance == 'Address':
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
                country_key = Country.all().filter("country =", country).get().key()
                if obj0:
                    obj0.adr = adr
                    obj0.location = db.GeoPt(lon=lon, lat=lat)
                    obj0.country = country_key
                    obj0.adr_zoom = adr_zoom
                else:
                    obj0 = Address(location=db.GeoPt(lon=lon, lat=lat), adr=adr,
                                  landline_phone=landline_phone, country=country_key,
                                  adr_zoom=adr_zoom,
                                  contact_ref=contact.key())
            elif instance == 'Mobile':
                mobile = db.PhoneNumber(self.request.get("mobile", ""))
                if obj0:
                    obj0.mobile = mobile
                else:
                    obj0 = Mobile(mobile=mobile, contact_ref=contact.key())
            elif instance == 'Web':
                web = db.Link(self.request.get("web", ""))
                if obj0:
                    obj0.web = web
                else:
                    obj0 = Web(web=web, contact_ref=contact.key())
            elif instance == 'Email':
                email = db.Email(self.request.get("email", ""))
                if obj0:
                    obj0.email = email
                else:
                    obj0 = Email(email=email, contact_ref=contact.key())
            elif instance == 'Other':
                what = self.request.get("what", "")
                # look for existing tag in DB
                tag = OtherTag.all().filter("tag =", what).get()
                if not tag:
                    tag = OtherTag(tag=what)
                    tag.put()
                text = self.request.get("text", "")
                if obj0:
                    obj0.what = what
                    obj0.tag = tag
                else:
                    obj0 = Other(tag=tag,text=text,contact_ref=contact.key())
            else:
                assert False, "Unhandled instance: %s" % (instance)
        except db.BadValueError:
            template_values['errors'] = ["Bad value error"]
        except ValueError:
            template_values['errors'] = ["Value error"]
        if 'errors' in template_values:
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), self.request.get("form_file"))
            self.response.out.write(template.render(path, template_values))
            return

        obj0.put()

        self.redirect('/editcontact?key=%s' % str(contact.key()))


def KeyRequired(target):
    """Decorator: Checks the requests arguments for the key and returns an error if not present.

    Besides the check, the function will also set the instance of the object represented by the key.
    """
    def error500():
        self.error(500)
        return

    def wrapper(self):
        key = self.request.get("key", "")
        if not key:
            return error500
        return target(self)

    return wrapper

class New(webapp.RequestHandler):
    """New property or contact"""

    def new_person(self, login_user=None, template_values={}):
        back_ref_key = self.request.get("key", None)

        if back_ref_key:
            # this is the person the new contact relates to (not necessarily the logged in user - me)
            back_ref = Person.get(back_ref_key)
            template_values['back_ref'] = back_ref_key
            template_values['back_ref_name'] = back_ref.name
            template_values['titlestr'] = "New contact for %s %s" % (back_ref.name, back_ref.lastname)
        else:
            template_values['titlestr'] = "New contact for %s %s" % (login_user.me.name, login_user.me.lastname)

        # all this stuff has to be in the form to have it ready if the
        # form has to be re-displayed after field error check (in PersonSave)
        template_values['form_file'] = 'take2form_person.html'
        template_values['instance'] = 'person'
        template_values['action'] = 'new'
        template_values.update(prepare_birthday_selectors())

        path = os.path.join(os.path.dirname(__file__), template_values['form_file'])
        self.response.out.write(template.render(path, template_values))

    def new_take2(self, login_user=None, template_values={}):
        """new take2 objects are this is handled by the edit handler"""

        uri = "/edit?action=new&instance=%s&key=%s" % (self.request.get("instance", ""),self.request.get("key", ""))
        self.redirect(uri)


    @MembershipRequired
    def get(self, login_user=None, template_values={}):
        instance = self.request.get("instance", Key(self.request.get("key")).kind())
        if instance == 'Person':
            New.new_person(self,login_user,template_values)
        elif instance == 'Company':
            New.new_person(self,login_user,template_values)
        elif instance == 'Contact':
            New.new_person(self,login_user,template_values)
        else:
            New.new_take2(self,login_user,template_values)


class Edit(webapp.RequestHandler):
    """Edit property or contact"""

    def edit_company(self, login_user=None, template_values={}):
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


    def edit_person(self, login_user=None, template_values={}):
        person_key = self.request.get("key", "")

        # this is the person we edit
        person = Person.get(person_key)

        # access rights check
        if not write_access(person,login_user):
            self.error(500)
            return

        template_values['link'] = None

        # define the html form fields for this object
        template_values['name'] = "%s %s" % (person.name,person.lastname)
        template_values['firstname'] = person.name
        if person.nickname:
            template_values['nickname'] = person.nickname
        if person.lastname:
            template_values['lastname'] = person.lastname
        template_values.update(prepare_birthday_selectors())
        template_values['birthday'] = str(person.birthday.get_day())
        template_values['birthmonth'] = str(person.birthday.get_month())
        template_values['birthyear'] = str(person.birthday.get_year())
        if person.back_ref:
            template_values['back_ref'] = str(person.back_ref.key())
            template_values['back_ref_name'] = person.back_ref.name
            titlestr = "Edit personal contact for %s %s" % (person.back_ref.name, person.back_ref.lastname)
        else:
            titlestr = "Edit Person data"
        if person.back_rel:
            template_values['back_rel'] = person.back_rel

        template_values['form_file'] = 'take2form_person.html'
        template_values['titlestr'] = titlestr
        template_values['instance'] = 'person'
        template_values['action'] = 'edit'
        template_values['key'] = person_key

        logging.debug(template_values)
        path = os.path.join(os.path.dirname(__file__), template_values['form_file'])
        self.response.out.write(template.render(path, template_values))


    def edit_take2(self, login_user=None, template_values={}):
        """Function is called to update a take2 object through a form

        The function prepares the data for the form. After the form is
        completed, a save function will store the new data."""
        action = self.request.get("action", "")
        instance = self.request.get("instance", "")
        key = self.request.get("key", "")
        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            t2 = Take2.get(key)
            # consistency checks on POSTed data
            assert t2.class_name() == instance, "Edit class name %s does not fit with object %s" % (instance,key)
            contact = t2.contact_ref
        else:
            # if a new property is added, key contains the contact key
            contact = Contact.get(key)

        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))

        # access check
        if not write_access(contact, login_user):
            self.error(500)
            return

        logging.debug("contact: %s action: %s instance: %s key: %s" %
                      (contact.name,action,instance,key))

        # title() capitalizes first letter
        titlestr = action.title()

        # define the html form fields for this take2 object
        form = []
        if instance == 'Address':
            titlestr = titlestr+" address"
            form_file = 'take2form_address.html'
            if action == 'edit':
                country = t2.country.country if t2.country else ""
                template_values['landlist'] = prepareListOfCountries(country)
                template_values['adr'] = "\n".join(t2.adr)
                if t2.location:
                    template_values['lat'] = t2.location.lat
                    template_values['lon'] = t2.location.lon
                template_values['landline_phone'] = "" if not t2.landline_phone else t2.landline_phone
                template_values['country'] = t2.country
                template_values['adr_zoom'] = ", ".join(t2.adr_zoom)
            else:
                template_values['landlist'] = prepareListOfCountries()
        elif instance == 'Mobile':
            titlestr = titlestr+" mobile phone"
            form_file = 'take2form_mobile.html'
            if action == 'edit':
                template_values['mobile'] = t2.mobile
        elif instance == 'Web':
            titlestr = titlestr+" website"
            form_file = 'take2form_web.html'
            if action == 'edit':
                template_values['web'] = t2.web
            else:
                template_values['web'] = 'http://'
        elif instance == 'Email':
            titlestr = titlestr+" email"
            form_file = 'take2form_email.html'
            if action == 'edit':
                template_values['email'] = t2.email
        elif instance == 'Other':
            titlestr = titlestr+" misc. info"
            form_file = 'take2form_other.html'
            # prepare drop down menu with preselected relation
            template_values['taglist'] = prepareListOfOtherTags()
            if action == 'edit':
                template_values['tag'] = t2.tag.tag
                template_values['text'] = t2.text
        else:
            assert False, "Unhandled take2 class: %s" % (take2_instance)

        template_values['titlestr'] = titlestr
        template_values['action'] = action
        if contact.class_name() == "Person":
            template_values['name'] = "%s %s" % (contact.name,contact.lastname)
        else:
            template_values['name'] = contact.name
        template_values['form'] = form
        template_values['instance'] = instance
        template_values['key'] = key
        template_values['form_file'] = form_file

        path = os.path.join(os.path.dirname(__file__), form_file)
        self.response.out.write(template.render(path, template_values))


    @KeyRequired
    @MembershipRequired
    def get(self, login_user=None, template_values={}):
        instance = self.request.get("instance", Key(self.request.get("key")).kind())
        if instance == 'Person':
            Edit.edit_person(self,login_user,template_values)
        elif instance == 'Company':
            Edit.edit_person(self,login_user,template_values)
        elif instance == 'Contact':
            Edit.edit_person(self,login_user,template_values)
        else:
            Edit.edit_take2(self,login_user,template_values)


class Attic(webapp.RequestHandler):
    """De-activate (archive) property or contact"""

    def attic_contact(self, login_user=None, template_values={}):
        key = self.request.get("key", "")

        contact = Contact.get(key)
        assert contact, "Object key: %s is not a Contact" % key
        # access check
        if not write_access(contact, login_user):
            self.error(500)
            return

        logging.debug("ContactAttic: %s key: %s" % (contact.name,key))

        contact.attic = True;
        contact.put();

        # if the contact had a backwards refrence, direkt to the middleman
        if contact.back_ref:
            key = str(contact.back_ref.key())

        self.redirect('/editcontact?key=%s' % key)


    def attic_take2(self, login_user=None, template_values={}):
        instance = self.request.get("instance", "")
        key = self.request.get("key", "")

        t2 = Take2.get(key)
        # consistency checks
        assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
        contact = t2.contact_ref
        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))
        # access check
        if not write_access(contact, login_user):
            self.error(500)
            return


        logging.debug("Attic: %s instance: %s key: %s" % (contact.name,instance,key))

        t2.attic = True;
        t2.put();

        self.redirect('/editcontact?key=%s' % str(contact.key()))

    @KeyRequired
    @MembershipRequired
    def get(self, login_user=None, template_values={}):
        instance = self.request.get("instance", Key(self.request.get("key")).kind())
        if instance in ['Person','Company','Contact']:
            Attic.attic_contact(self,login_user,template_values)
        else:
            Attic.attic_take2(self,login_user,template_values)



class Deattic(webapp.RequestHandler):
    """Re-activate a property or contact from archive"""

    def deattic_contact(self, login_user=None, template_values={}):
        key = self.request.get("key", "")

        contact = Contact.get(key)
        assert contact, "Object key: %s is not a Contact" % (key)
        # access check
        assert contact.owned_by.key() == login_user.key(), "User %s cannot manipulate %s" % (login_user.user.nickname(),str(contact.key()))

        logging.debug("ContactDeattic: %s key: %s" % (contact.name,key))

        contact.attic = False;
        contact.put();

        self.redirect('/editcontact?key=%s' % key)

    def deattic_take2(self, login_user=None, template_values={}):
        instance = self.request.get("instance", "")
        key = self.request.get("key", "")

        t2 = Take2.get(key)
        # consistency checks
        assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
        contact = t2.contact_ref
        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))
        # access check
        if not write_access(contact, login_user):
            self.error(500)
            return

        logging.debug("De-attic: %s instance: %s key: %s" % (contact.name,instance,key))

        t2.attic = False;
        t2.put();

        self.redirect('/editcontact?key=%s' % str(contact.key()))


    @KeyRequired
    @MembershipRequired
    def get(self, login_user=None, template_values={}):
        instance = self.request.get("instance", Key(self.request.get("key")).kind())
        if instance in ['Person','Company','Contact']:
            Deattic.deattic_contact(self,login_user,template_values)
        else:
            Deattic.deattic_take2(self,login_user,template_values)


class Edittest(webapp.RequestHandler):
    """Re-activate a property from archive"""

    def get(self):
        path = os.path.join(os.path.dirname(__file__), 'take2search1.html')
        self.response.out.write(template.render(path, {}))


application = webapp.WSGIApplication([('/editcontact', ContactEdit),
                                      ('/savecompany', CompanySave),
                                      ('/saveperson', PersonSave),
                                      ('/edittest', Edittest),
                                      ('/edit.*', Edit),
                                      ('/new.*', New),
                                      ('/save.*', Take2Save),
                                      ('/attic.*', Attic),
                                      ('/deattic.*', Deattic),
                                     ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

