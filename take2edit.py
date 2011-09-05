"""Take2 search and edit REST Api"""

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
            con = encodeContact(contact, attic=False)
            con['birthday'] = "%d %s" % (contact.birthday.day,
                                         calendar.month_name[contact.birthday.month])
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
                # change birthday encoding from yyyy-mm-dd to dd Month
                con['birthday'] = "%d %s" % (contact.birthday.day,
                                             calendar.month_name[contact.birthday.month])
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

        action,instance,key = self.request.get("action", "").split("_")
        assert action in ['new','edit'], "Undefined action: %s" % (action)
        assert instance in ['person','contact'], "Undefined instance type: %s" % (action)

        if action == 'edit':
            contact = Contact.get(key)

        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))

        # title() capitalizes first letter
        titlestr = action.title()

        template_values = {}
        # define the html form fields for this take2 object
        form = []
        if action == 'edit':
            if contact.class_name() == "Person":
                form.append('<input type="text" name="name" value="%s">' % contact.name)
                form.append('<input type="text" name="nickname" value="%s">' % contact.nickname)
                form.append('<input type="text" name="lastname" value="%s">' % contact.lastname)
                form.append('<br><input type="text" name="birthday" value="%s"><div id="birthday_format">dd/mm/yyyy (replace unknown year with 0000)' % contact.birthday)
            else:
                form.append('<input type="text" name="name" value="%s">' % contact.name)
        else:
            if instance == 'person':
                form.append('<input type="text" name="name" >')
                form.append('<input type="text" name="nickname" >')
                form.append('<input type="text" name="lastname" >')
                form.append('<br><input type="text" name="birthday" ><div id="birthday_format">dd/mm/yyyy (replace unknown year with 0000)</div>')
            else:
                form.append('<input type="text" name="name" >')

        template_values['titlestr'] = titlestr
        template_values['action'] = action
        if contact.class_name() == "Person":
            template_values['name'] = contact.name+" "+contact.lastname
        else:
            template_values['name'] = contact.name
        template_values['contact'] = contact
        template_values['form'] = form
        template_values['form_action'] = "/savecontact"
        template_values['instance'] = instance
        template_values['key'] = key

        path = os.path.join(os.path.dirname(__file__), 'take2edit.html')
        self.response.out.write(template.render(path, template_values))


class ContactSave(webapp.RequestHandler):
    """Update/Save contact"""

    def post(self):
        user = users.get_current_user()


class Take2Edit(webapp.RequestHandler):
    """Edit existing properties or add something new"""

    def post(self):
        user = users.get_current_user()

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
        if instance == 'mobile':
            titlestr = titlestr+" mobile phone"
            if action == 'edit':
                form.append('<input type="text" name="mobile" value="%s">' % t2.mobile)
            else:
                form.append('<input type="text" name="mobile">')
        else:
            assert True, "Unhandled take2 class: %s" % (take2_instance)

        template_values['titlestr'] = titlestr
        template_values['action'] = action
        if contact.class_name() == "Person":
            template_values['name'] = contact.name+" "+contact.lastname
        else:
            template_values['name'] = contact.name
        template_values['contact'] = contact
        template_values['form'] = form
        template_values['form_action'] = "/save"
        template_values['instance'] = instance
        template_values['key'] = key

        path = os.path.join(os.path.dirname(__file__), 'take2edit.html')
        self.response.out.write(template.render(path, template_values))


class Take2Save(webapp.RequestHandler):
    """Save users/properties"""

    def post(self):
        user = users.get_current_user()

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

        assert contact.class_name() == 'Person' or contact.class_name() == 'Contact', "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))

        logging.debug("contact: %s instance: %s key: %s" %
                    (contact.name,instance,key))

        #
        # update database
        #

        if instance == 'mobile':
            if action == 'new':
                mobile = Mobile(mobile=self.request.get("mobile", ""), contact=contact.key())
                mobile.put()
            else:
                # update means creation of a new object, old object points to new one
                # TODO: In one transaction
                mobile1 = Mobile(mobile=self.request.get("mobile", ""), contact=contact.key())
                mobile1.put()
                mobile0 = Mobile.get(key)
                mobile0.contact = mobile1.key()
                mobile0.put()
        else:
            assert True, "Unhandled instance: %s" % (instance)

        self.redirect('/search?key=%s' % str(contact.key()))

application = webapp.WSGIApplication([('/search.*', Take2Search),
                                      ('/edit', Take2Edit),
                                      ('/editcontact', ContactEdit),
                                      ('/savecontact', ContactSave),
                                      ('/save', Take2Save),
                                     ],debug=True)

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

