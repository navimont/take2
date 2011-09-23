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
from google.appengine.api import memcache
from take2dbm import Contact, Person, Company, Take2, FuzzyDate
from take2dbm import Link, Email, Address, Mobile, Web, Other, Country
from take2export import encode_contact
from take2access import get_current_user_person, get_current_user_template_values, MembershipRequired, visible_contacts

def encode_contact_for_webpage(dump, contact, me):
    """Revises some field in the db dump (a strcuture of lists and dictionaries)
    so that the data can be used for the template renderer

    dump: contact data dump used for webpage output
    contact: db Contact class (a Person or Company instance)
    me: Person class representing the logged in user
    """
    if contact.class_name() == "Person":
        # birthdays are displayed without the year of birth
        if 'birthday' in dump:
            dump['birthday'] = "%d %s" % (contact.birthday.day,
                                         calendar.month_name[contact.birthday.month])
    # find the contact's relation to me (the person who is looged in)
    dump['relation_to_me'] = None
    if me:
        if me.key() == contact.key():
            dump['relation_to_me'] = "%s, that's you!" % (contact.name)
            dump['myself'] = True
        else:
            # find my link to the contact
            q_rel = Link.all()
            q_rel.filter("contact =", me)
            q_rel.filter("link_to =", contact)
            rel = q_rel.fetch(1)
            if len(rel) > 0:
                assert len(rel) == 1, "too many links from: %s to: %s" % (str(me.key(),str(contact.key())))
                rel = rel[0]
                if contact.class_name() == "Person":
                    dump['relation_to_me'] = "%s is your %s." % (contact.name,rel.link.lower())
                else:
                    dump['relation_to_me'] = "Your relation: %s" % (rel.link.lower())

    return dump



class Take2Search(webapp.RequestHandler):
    """Run a search query over the current user's realm"""

    def get(self):
        user = users.get_current_user()
        signed_in = True if user else False
        me = get_current_user_person(user)
        template_values = get_current_user_template_values(user,self.request.uri)

        query = self.request.get('query',"")
        contact_key = self.request.get('key',"")
        if self.request.get('attic',"") == 'True':
            archive = True
        else:
            archive = False

        logging.debug("Search query: %s archive: %d key: %s " % (query,archive,contact_key))

        result = []

        #
        # key is given
        #

        if contact_key:
            contact = Contact.get(contact_key)
            # this is basically a db dump
            con = encode_contact(contact, include_attic=False, signed_in=signed_in, me=me)
            # adjust fields and add extra fields for website renderer
            con = encode_contact_for_webpage(con, contact, me)
            result.append(con)

        #
        # query search
        #

        if query:
            q_res = []
            query1 = query+u"\ufffd"
            logging.debug("Search for %s >= name < %s" % (query,query1))
            q_con = Contact.all()
            q_con.filter("attic =", False)
            q_con.filter("name >=", query).filter("name <", query1)
            q_res.extend(q_con)
            template_values['query'] = query

            for contact in q_res:
                con = encode_contact(contact, include_attic=False, signed_in=signed_in, me=me)
                # adjust fields and add extra fields for website renderer
                con = encode_contact_for_webpage(con, contact, me)
                result.append(con)
        else:
            # display current user data
            if me:
                con = encode_contact(me, include_attic=False, signed_in=signed_in, me=me)
                # adjust fields and add extra fields for website renderer
                con = encode_contact_for_webpage(con, me, me)
                result.append(con)

        #
        # birthday search
        #

        if me:
            # read from cache if possible
            template_values['birthdays'] = memcache.get('birthdays',namespace=str(me.key()))
            if not template_values['birthdays']:
                daterange_from = datetime.today() - timedelta(days=5)
                daterange_to = datetime.today() + timedelta(days=14)
                # Convert to fuzzydate and then to int (that's how it is stored in the db).
                # Year is least important
                fuzzydate_from = FuzzyDate(day=daterange_from.day,
                                          month=daterange_from.month).to_int()
                fuzzydate_to = FuzzyDate(day=daterange_to.day,
                                          month=daterange_to.month).to_int()
                if fuzzydate_from > fuzzydate_to:
                    # end-of-year turnover
                    fuzzydate_to_1 = 12310000
                    fuzzydate_from_1 = 1010000
                else:
                    fuzzydate_from_1 = fuzzydate_from
                    fuzzydate_to_1 = fuzzydate_to
                logging.debug("Birthday search from: %d to %d OR  %d to %d" % (fuzzydate_from,fuzzydate_to_1,fuzzydate_from_1,fuzzydate_to))
                # whose birthdays can I see?
                vcon = visible_contacts(me)
                # now find the ones with birthdays in the range
                template_values['birthdays'] = []
                for ckey in vcon:
                    con = Contact.get(ckey)
                    # skip companies
                    if con.class_name() != "Person":
                        continue
                    if ((con.birthday.to_int() > fuzzydate_from and con.birthday.to_int() <= fuzzydate_to_1)
                        or (con.birthday.to_int() > fuzzydate_from_1 and con.birthday.to_int() <= fuzzydate_to)):
                        jubilee = {}
                        # change birthday encoding from yyyy-mm-dd to dd Month
                        jubilee['birthday'] = "%d %s" % (con.birthday.get_day(),
                                                        calendar.month_name[con.birthday.get_month()])
                        jubilee['name'] = con.name
                        # find the nickname
                        link = Link.all().filter("link_to =", ckey).filter("contact =", me).get()
                        if link:
                            jubilee['nickname'] = link.nickname
                        template_values['birthdays'].append(jubilee)
                        # store in memcache
                        memcache.set('birthdays',template_values['birthdays'],namespace=str(me.key()))

        # render search result page
        template_values['result'] = result
        path = os.path.join(os.path.dirname(__file__), 'take2search.html')
        self.response.out.write(template.render(path, template_values))



application = webapp.WSGIApplication([('/search.*', Take2Search),
                                      ],debug=True)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

