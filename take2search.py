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
from take2access import get_login_user, get_current_user_template_values, MembershipRequired, visible_contacts
from take2contact_index import lookup_contacts

class Take2Overview(object):
    def __init__(self,headertext,class_name):
        self.header = headertext
        self.data = []
        self.has_attic = False
        self.class_name = class_name

    def append_take2(self,obj):
        """obj is a Take2View subclass (Take2email etc.)"""
        if obj.attic:
            self.has_attic = True
        self.data.append(obj)

class Take2View(object):
    def __init__(self,obj):
        self.class_name = str(obj.key())
        self.attic = obj.attic

class EmailView(Take2View):
    def __init__(self, obj):
        super(EmailView, self).__init__(obj)
        self.data = obj.email

class WebView(Take2View):
    def __init__(self, obj):
        super(WebView, self).__init__(obj)
        self.data = obj.web

class MobileView(Take2View):
    def __init__(self, obj):
        super(MobileView, self).__init__(obj)
        self.data = obj.mobile

class OtherView(Take2View):
    def __init__(self, obj):
        super(OtherView, self).__init__(obj)
        self.data = "%s %s" % (obj.what, obj.text)
        self.what = obj.what
        self.text = obj.text

class AddressView(Take2View):
    def __init__(self,obj):
        super(AddressView, self).__init__(obj)
        if obj.location:
            self.location_lat = obj.location.lat
            self.location_lon = obj.location.lon
        self.adr = obj.adr
        if obj.landline_phone:
            self.landline_phone = obj.landline_phone
        if obj.country:
            self.country = obj.country.country
        if obj.adr_zoom:
            self.adr_zoom = obj.adr_zoom
        self.data = "%s %s" % (", ".join(self.adr),self.country)

class LinkView(Take2View):
    def __init__(self,obj):
        super(LinkView, self).__init__(obj)
        if obj.nickname:
            self.data = "%s (%s) %s" % (obj.link_to.name,obj.nickname,obj.link_to.lastname)
        else:
            self.data = "%s %s" % (obj.link_to.name,obj.link_to.lastname)
        self.link = obj.link
        self.link_to = str(obj.link_to.key())
        self.nickname = obj.nickname
        self.name = obj.link_to.name
        self.lastname = obj.link_to.lastname

class ContactView():
    def __init__(self,contact):
        self.name = contact.name
        self.attic = contact.attic
        self.key = str(contact.key())
        self.class_name = contact.class_name()
        self.email = Take2Overview('Email','Email')
        self.mobile = Take2Overview('Mobile Phone','Mobile')
        self.web = Take2Overview('Web site','Web')
        self.link = Take2Overview('Contacts, friends & family','Link')
        self.other = Take2Overview('Miscellaneous','Other')
        self.address = Take2Overview('Street address','Address')
        self.relations = []

    def append_relation(self,relation):
        self.relations.append(relation)

    def append_take2(self, obj):
        """Receive a take2 object, create a Take2View representation
        for it and make it part of the ContactView class."""
        if obj.class_name() == "Email":
            self.email.append_take2(EmailView(obj))
        elif obj.class_name() == "Web":
            self.web.append_take2(WebView(obj))
        elif obj.class_name() == "Mobile":
            self.mobile.append_take2(MobileView(obj))
        elif obj.class_name() == "Other":
            self.other.append_take2(OtherView(obj))
        elif obj.class_name() == "Address":
            self.address.append_take2(AddressView(obj))
        elif obj.class_name() == "Link":
            self.link.append_take2(LinkView(obj))
        # create a take2 list of Take2Overview objects but
        # only those which contain data
        self.take2 = []
        for t2 in [self.link,self.email,self.mobile,self.web,self.address,self.other]:
            if t2.data:
                self.take2.append(t2)


def encode_contact(contact, login_user, include_attic=False):
    """Factory to encode data into view classes which can easily be rendered

    The function takes into account the access rights and encodes only elements
    which the user is allowed to see.
    signed_in is set to True if the user is signed in
    If attic=True, data will include the complete history and also archived data.
    """
    result = None
    # do only enclose non-attic contacts unless attic parameter is set
    if contact.attic and not include_attic:
        return None

    result = ContactView(contact)

    if not login_user:
        # the name is all which anonymous users will see
        return result

    if contact.class_name() == "Person":
        if contact.lastname:
            result.lastname = contact.lastname

    # In order to reveal more data, we must check if 'me' is allowed
    # to see it.
    visible = visible_contacts(login_user, include_attic)
    if not (contact.key() in visible):
        return result

    # Birthday
    if contact.class_name() == "Person":
        if contact.birthday.has_year():
            result.birthyear = contact.birthday.year
        if contact.birthday.has_month():
            result.birthmonth = calendar.month_name[contact.birthday.month]
        if contact.birthday.has_day():
            result.birthday = contact.birthday.day

    # Relation regarding this person (who points towards this contact and why?)
    q_rel = Link.all()
    q_rel.filter("link_to =", contact)
    for rel in q_rel:
        if rel.link:
            result.append_relation(rel.link)

    # can I edit the contact data?
    if login_user and login_user.me:
        if contact.owned_by.key() == login_user.key():
            result.can_edit = True

    #
    # encode contact's data
    #
    q_obj = Take2.all()
    q_obj.filter("contact_ref =", contact)
    q_obj.order('-timestamp')
    for obj in q_obj:
        # do only enclose non-attic take2 properties unless attic parameter is set
        if obj.attic and not include_attic:
            continue

        result.append_take2(obj)

    return result


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

        result = []

        #
        # key is given
        #

        if contact_key:
            contact = Contact.get(contact_key)
            # this is basically a db dump
            con = encode_contact(contact, include_attic=False, login_user=login_user)
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
                result.append(con)
        else:
            # display current user data
            if login_user:
                con = encode_contact(login_user.me, include_attic=False, login_user=login_user)
                result.append(con)
                for take2 in con.take2:
                    logging.debug(take2.header)
                    for data in take2.data:
                        logging.debug(data.data)

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

