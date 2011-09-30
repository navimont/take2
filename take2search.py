"""Take2 search REST Api

Supports searches for Contacts
Maintains a quick contact index table for simplified search and autocompletion
"""

import settings
import logging
import os
import calendar
from datetime import datetime, timedelta
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.api import taskqueue
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import memcache
from take2dbm import Contact, Person, Company, Take2, FuzzyDate, ContactIndex, PlainKey
from take2dbm import Link, Email, Address, Mobile, Web, Other, Country
from take2export import encode_contact
from take2access import get_login_user, get_current_user_template_values, MembershipRequired, visible_contacts
from take2contact_index import lookup_contacts

def encode_contact_for_webpage(dump, contact, login_user):
    """Revises some field in the db dump (a strcuture of lists and dictionaries)
    so that the data can be used for the template renderer

    dump: contact data dump used for webpage output
    contact: db Contact class (a Person or Company instance)
    """
    if contact.class_name() == "Person":
        # birthdays are displayed without the year of birth
        if 'birthday' in dump:
            dump['birthday'] = "%d %s" % (contact.birthday.day,
                                         calendar.month_name[contact.birthday.month])
    # find the contact's relation to me (the person who is looged in)
    dump['relation_to_me'] = None
    if login_user and login_user.me:
        # if contact is owned by me, I can edit it
        if contact.owned_by.key() == login_user.key():
            dump['can_edit'] = True

        if login_user.me.key() == contact.key():
            dump['relation_to_me'] = "%s, that's you!" % (contact.name)
            dump['myself'] = True
        else:
            # find a contact's nickname
            q_rel = Link.all()
            q_rel.filter("contact_ref =", login_user.me)
            q_rel.filter("link_to =", contact)
            rel = q_rel.fetch(1)
            if len(rel) > 0:
                assert len(rel) == 1, "too many links from: %s to: %s" % (str(login_user.me.key(),str(contact.key())))
                rel = rel[0]
                dump['relation_to_me'] = rel.link
                if contact.class_name() == "Person":
                    dump['nickname'] = rel.nickname

        # This contact's connections
        for ln in dump['link']:
            # load linked object from database
            link = Contact.get(Key(ln['link_to']))
            ln['name'] = link.name
            ln['lastname'] = link.lastname

    # add information whether a property has deleted (attic) elements
    for instance in ['email','web','address','mobile','other']:
        if instance in dump:
            for t2 in dump[instance]:
                if 'attic' in t2 and  t2['attic']:
                    dump["%s_attic" % (instance)] = True


    return dump


class Take2Search(webapp.RequestHandler):
    """Run a search query over the current user's realm"""

    def get(self):
        google_user = users.get_current_user()
        signed_in = True if google_user else False
        login_user = get_login_user(google_user)
        template_values = get_current_user_template_values(google_user,self.request.uri)

        # no connection between signed in user and any person in the database
        if login_user and not login_user.me:
            # prepare list of days and months
            daylist = ["(skip)"]
            daylist.extend(range(1,32))
            template_values['daylist'] = daylist
            monthlist=[(str(i),calendar.month_name[i]) for i in range(13)]
            monthlist[0] = ("0","(skip)")
            template_values['monthlist'] = monthlist
            path = os.path.join(os.path.dirname(__file__), 'take2welcome.html')
            self.response.out.write(template.render(path, template_values))
            return

        query = self.request.get('query',"")
        contact_key = self.request.get('key',"")
        if self.request.get('attic',"") == 'True':
            archive = True
        else:
            archive = False

        logging.debug("Search query: %s archive: %d key: %s " % (query,archive,contact_key))

        # Once in a while invoke task queue to refresh the index table
        if not memcache.get('contact_index'):
            memcache.set('contact_index', True, time=settings.CONTACT_INDEX_REFRESH)
            # Add the task to the default queue.
            taskqueue.add(url='/index')

        result = []

        #
        # key is given
        #

        if contact_key:
            contact = Contact.get(contact_key)
            # this is basically a db dump
            con = encode_contact(contact, include_attic=False, login_user=login_user)
            # adjust fields and add extra fields for website renderer
            con = encode_contact_for_webpage(con, contact, login_user)
            result.append(con)

        #
        # query search
        #

        elif query:
            cis = lookup_contacts(query, 100, first_call=True)
            # TODO implement various pages for lng result lists
            template_values['query'] = query
            for contact in cis:
                con = encode_contact(contact, include_attic=False, login_user=login_user)
                # adjust fields and add extra fields for website renderer
                con = encode_contact_for_webpage(con, contact, login_user)
                result.append(con)
        else:
            # display current user data
            if login_user:
                con = encode_contact(login_user.me, include_attic=False, login_user=login_user)
                # adjust fields and add extra fields for website renderer
                con = encode_contact_for_webpage(con, login_user.me, login_user)
                result.append(con)

        #
        # birthday search
        #

        if login_user:
            # read from cache if possible
            template_values['birthdays'] = memcache.get('birthdays',namespace=str(login_user.key()))
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
                vcon = visible_contacts(login_user)
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
                        link = Link.all().filter("link_to =", ckey).filter("contact =", login_user.me).get()
                        if link:
                            jubilee['nickname'] = link.nickname
                        template_values['birthdays'].append(jubilee)
                # store in memcache
                memcache.set('birthdays',template_values['birthdays'],time=60*60*24,namespace=str(login_user.key()))

        # render search result page
        template_values['result'] = result
        path = os.path.join(os.path.dirname(__file__), 'take2search.html')
        self.response.out.write(template.render(path, template_values))



application = webapp.WSGIApplication([('/', Take2Search),
                                      ('/search.*', Take2Search),
                                      ],debug=settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

