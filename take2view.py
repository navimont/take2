"""Take2 encoding data structures for viewing data on the web page

"""

import settings
import logging
import os
import calendar
from google.appengine.ext import db
from take2dbm import Contact, Person, Company, Take2, FuzzyDate, ContactIndex, PlainKey
from take2dbm import Link, Email, Address, Mobile, Web, Other, Country
from take2access import visible_contacts

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
        self.key = str(obj.key())
        self.class_name = obj.class_name()
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
        self.data = "%s %s" % (obj.tag.tag, obj.text)
        self.tag = obj.tag.tag
        self.text = obj.text

class AddressView(Take2View):
    def __init__(self,obj):
        super(AddressView, self).__init__(obj)
        if obj.location:
            self.location_lat = obj.location.lat
            self.location_lon = obj.location.lon
        self.adr = obj.adr
        self.landline_phone = obj.landline_phone if obj.landline_phone else ""
        self.country = obj.country.country if obj.country else ""
        self.adr_zoom = obj.adr_zoom if obj.adr_zoom else ""
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
