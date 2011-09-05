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
        if self.request.get('attic',"") == 'True':
            archive = True
        else:
            archive = False

        template_values = {'nickname': user.nickname()}

        #
        # query search
        #

        q_res = []
        query1 = query+u"\ufffd"
        logging.debug("Search for %s >= name < %s" % (query,query1))
        q_con = Contact.all()
        q_con.filter("name >=", query).filter("name <", query1)
        q_res.extend(q_con)
        template_values['query'] = query

        result = []
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



class Take2Edit(webapp.RequestHandler):
    """Edit existing users/properties or add something new"""

    def post(self):
        user = users.get_current_user()

        action,take2,key = self.request.get("action", "").split("_")
        contact_key = self.request.get("contact_key", "")
        contact = Contact.get(contact_key)

        logging.debug("contact: %s action: %s property: %s key: %s" % (contact.name,action,take2,key))

        if action == 'edit':
            t2 = Take2.get(key)
            # make some consistency checks on POSTed data
            assert t2.class_name() == take2.title(), "Edit class name %s does not fit with object %s" % (take2,key)
            assert t2.contact.key() == contact.key(), "Contact %s key: %s is not referenced by object %s" % (contact.name,str(contact.key()),str(t2.key()))
        elif action == 'new':
            pass
        else:
            assert True, "Undefined action: %s" % (action)
        # capitalize first letter
        actionstr = action.title()

        template_values = {}
        # define the html form fields for this take2 object
        form = []
        if take2 == 'mobile':
            actionstr = actionstr+" mobile phone"
            if action == 'edit':
                form.append('<input type="text" name="mobile" value="%s">' % t2.mobile)
            else:
                form.append('<input type="text" name="mobile">')
        else:
            assert True, "Unhandled take2 class: %s" % (take2)
        template_values['action'] = actionstr
        if contact.class_name() == "Person":
            template_values['name'] = contact.name+" "+contact.lastname
        else:
            template_values['name'] = contact.name
        template_values['contact'] = contact
        template_values['form'] = form

        path = os.path.join(os.path.dirname(__file__), 'take2edit.html')
        self.response.out.write(template.render(path, template_values))




application = webapp.WSGIApplication([('/search.*', Take2Search),
                                      ('/edit.*', Take2Edit),
                                     ],debug=True)

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

