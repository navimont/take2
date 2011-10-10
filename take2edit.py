"""Take2 edit REST Api. Controls the pages and the workflow to

Save NEW contacts and their properties (addresses, email and the like, all of object type Take2)
EDIT exsiting data
ATTIC and DEATTIC (make disappear and re-appear obsolete entries)
"""

import settings
import logging
import os
import calendar
from datetime import datetime, timedelta
import yaml
from django.utils import simplejson as json
from django.core.exceptions import ValidationError
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from take2dbm import Person, Contact, Take2
from take2access import MembershipRequired, write_access, visible_contacts
from take2view import encode_contact
from take2index import check_and_store_key
from take2beans import PersonBean, EmailBean, MobileBean, AddressBean, WebBean, OtherBean

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



class Save(webapp.RequestHandler):
    """Save Contact or Take2 entity

    This request handler is as the form action called after take2form.html was displayed.
    It checks and saves all data which was displayed in the form. An input value 'instance'
    contains a list of comma separated instance names of the data classes which were
    visible in the form. E.g. "Person,Email,Address"

    If data was new (not loaded from the database) there are no <Class_name>_key
    """

    @MembershipRequired
    def post(self, login_user=None, template_values={}):
        instance = self.request.get("instance", "")
        instance_list = instance.split(",")
        contact_ref = self.request.get("contact_ref", None)

        # contact_ref points to the person to which the take2 entries in this form
        # belong to.
        # The only case that it won't exist in the input form is if a new contact
        # (Person) is saved.
        contact = None
        if contact_ref:
            contact = Contact.get(contact_ref)
            # access rights check
            if not write_access (contact, login_user):
                self.error(500)
                return
            template_values['titlestr'] = "Address book entry for %s %s" % (contact.name, contact.lastname)
        else:
            # otherwise for the login_user
            template_values['titlestr'] = "New address book entry for %s %s" % (login_user.me.name, login_user.me.lastname)

        template_values['errors'] = []
        if 'Person' in instance_list:
            person = PersonBean.edit(login_user,self.request)
            template_values.update(person.get_template_values())
            err = person.validate()
            if not err:
                person.put()
            else:
                template_values['errors'].extend(err)
            # This is now the person to which the take2 data relates
            contact = person.get_entity()

        # go through all take2 types
        for (bean_name,bean_class) in (('Email',EmailBean),('Mobile',MobileBean),('Address',AddressBean),
                                        ('Web',WebBean),('Other',OtherBean)):
            if bean_name in instance_list:
                obj = bean_class.edit(contact, self.request)
                template_values.update(obj.get_template_values())
                err = obj.validate()
                if not err:
                    obj.put()
                else:
                    # If the object is there in conjunction with the person that
                    # means it's just not filled in. We save only the person, that's fine
                    if 'Person' in instance_list:
                        continue
                    template_values['errors'].extend(err)


        # if errors happened, re-display the form
        if template_values['errors']:
            template_values['instance_list'] = instance_list
            template_values['instance'] = instance
            template_values['contact_ref'] = contact_ref
            path = os.path.join(os.path.dirname(__file__), 'take2form.html')
            self.response.out.write(template.render(path, template_values))
            return


        self.redirect('/editcontact?key=%s' % str(contact.key()))



class New(webapp.RequestHandler):
    """New property or contact"""

    @MembershipRequired
    def get(self, login_user=None, template_values={}):
        instance = self.request.get("instance", "")
        instance_list = instance.split(",")
        # key
        contact_ref = self.request.get("contact_ref", None)

        if 'Person' in instance_list:
            # the presence of the key indicates that the new person shall be
            # created with reference (middleman_ref) to key.
            if contact_ref:
                person = PersonBean.new_person_via_middleman(login_user,middleman_ref=contact_ref)
            else:
                person = PersonBean.new_person(login_user)
            template_values.update(person.get_template_values())
        # go through all take2 types
        for (bean_name,bean_class) in (('Email',EmailBean),('Mobile',MobileBean),('Address',AddressBean),
                                        ('Web',WebBean),('Other',OtherBean)):
            if bean_name in instance_list:
                obj = bean_class.new(contact_ref)
                template_values.update(obj.get_template_values())

        if contact_ref:
            # if contact is specified, the new entry is for this person
            contact = Person.get(contact_ref)
            template_values['titlestr'] = "New address book entry for %s %s" % (contact.name, contact.lastname)
            template_values['contact_ref'] = contact_ref
        else:
            # otherwise for the login_user
            template_values['titlestr'] = "New address book entry for %s %s" % (login_user.me.name, login_user.me.lastname)
            template_values['contact_ref'] = str(login_user.me.key())

        # instances as list and as concatenated string
        template_values['instance_list'] = instance_list
        template_values['instance'] = instance

        path = os.path.join(os.path.dirname(__file__), 'take2form.html')
        self.response.out.write(template.render(path, template_values))


class Edit(webapp.RequestHandler):
    """Edit property or contact"""

    @MembershipRequired
    def get(self, login_user=None, template_values={}):
        """Function is called to update a take2 object or a contact.

        The function prepares the data for the form. After the form is
        completed, a save function will store the new data."""
        instance = self.request.get("instance", "")
        instance_list = instance.split(",")
        contact_ref = self.request.get("contact_ref", None)

        # contact_ref points to the person to which the take2 entries in this form
        # belong to.
        assert contact_ref, "No contact_ref received."

        contact = Contact.get(contact_ref)
        # access rights check
        if not write_access (contact, login_user):
            self.error(500)
            return

        template_values['titlestr'] = "Address book entry for %s %s" % (contact.name, contact.lastname)

        #
        # Use beans to prepare form data
        #
        for (bean_name,bean_class) in (('Person',PersonBean),('Email',EmailBean),('Mobile',MobileBean),
                                        ('Address',AddressBean),('Web',WebBean),('Other',OtherBean)):
            if bean_name in instance_list:
                key = self.request.get('%s_key' % bean_name, None)
                if not key and not bean_name == 'Person':
                    # We simply treat this as a new object
                    obj = bean_class.new(contact_ref)
                else:
                    obj = bean_class.load(key)
                template_values.update(obj.get_template_values())

        # instances as list and as concatenated string
        template_values['instance_list'] = instance_list
        template_values['instance'] = instance
        template_values['contact_ref'] = contact_ref

        path = os.path.join(os.path.dirname(__file__), 'take2form.html')
        self.response.out.write(template.render(path, template_values))


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
        if contact.middleman_ref:
            key = str(contact.middleman_ref.key())

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

    @MembershipRequired
    def get(self, login_user=None, template_values={}):
        instance = self.request.get("instance", Key(self.request.get("key")).kind())
        if instance in ['Person','Company','Contact']:
            Deattic.deattic_contact(self,login_user,template_values)
        else:
            Deattic.deattic_take2(self,login_user,template_values)



application = webapp.WSGIApplication([('/editcontact', ContactEdit),
                                      ('/edit.*', Edit),
                                      ('/new.*', New),
                                      ('/save.*', Save),
                                      ('/attic.*', Attic),
                                      ('/deattic.*', Deattic),
                                     ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

