"""Take2 encoding data structures for viewing data on the web page

"""

import settings
import logging
import os
import calendar
from google.appengine.ext import db
from take2dbm import Contact, Person, Company, Take2, FuzzyDate, ContactIndex, PlainKey
from take2dbm import Email, Address, Mobile, Web, Other, Country, SharedTake2
from take2access import visible_contacts

class Take2Overview(object):
    def __init__(self,headertext,class_name):
        self.header = headertext
        self.data = []
        self.has_attic = False
        self.has_data = False
        self.class_name = class_name

    def append_take2(self,obj):
        """obj is a Take2View subclass (Take2email etc.)"""
        if obj.attic:
            self.has_attic = True
        self.has_data = True
        self.data.append(obj)

class Take2View(object):
    def __init__(self,obj):
        self.key = str(obj.key())
        self.class_name = obj.class_name()
        self.attic = obj.attic
        try:
            self.privacy = obj.privacy
        except AttributeError:
            self.privacy = 'private'

class AffixView(Take2View):
    def __init__(self, obj):
        super(AffixView, self).__init__(obj)
        # overwrite wrong class_name (would be Person)
        self.class_name = obj.class_name()
        self.name = obj.name
        self.data = obj.name
        if obj.class_name() == 'Person':
            self.lastname = obj.lastname if obj.lastname else ""
            self.data = "%s %s" % (self.name,self.lastname)
            if obj.nickname:
                self.nickname = obj.nickname
                self.data = "%s (%s) %s" % (self.name,self.nickname,self.lastname)

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
        self.text = obj.text
        if obj.tag:
            self.tag = obj.tag.tag
            self.data = "%s %s" % (obj.tag.tag, obj.text)
        else:
            self.data = self.text

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

class ContactView():
    def __init__(self,contact):
        self.name = contact.name
        self.attic = contact.attic
        self.key = str(contact.key())
        self.class_name = contact.class_name()
        self.affix = Take2Overview('Contacts, Family & Friends','Person')
        self.email = Take2Overview('Email','Email')
        self.mobile = Take2Overview('Mobile Phone','Mobile')
        self.web = Take2Overview('Web site','Web')
        self.other = Take2Overview('Miscellaneous','Other')
        self.address = Take2Overview('Street address','Address')
        self.take2 = [self.affix,self.email,self.mobile,self.web,self.address,self.other]

    def append_relation(self,relation):
        self.relations.append(relation)

    def append_take2(self, obj):
        """Receive a take2 object, create a Take2View representation
        for it and make it part of the ContactView class."""
        if obj.class_name() == "Email":
            self.email.append_take2(EmailView(obj))
        elif obj.class_name() == "Web":
            self.web.append_take2(WebView(obj))
        elif obj.class_name() == "Person":
            self.affix.append_take2(AffixView(obj))
        elif obj.class_name() == "Company":
            self.affix.append_take2(AffixView(obj))
        elif obj.class_name() == "Mobile":
            self.mobile.append_take2(MobileView(obj))
        elif obj.class_name() == "Other":
            self.other.append_take2(OtherView(obj))
        elif obj.class_name() == "Address":
            self.address.append_take2(AddressView(obj))


def encode_contact(contact, login_user, include_attic=False, include_privacy=False):
    """Factory to encode data into view classes which can easily be rendered

    The function takes into account the access rights and encodes only elements
    which the user is allowed to see.
    signed_in is set to True if the user is signed in
    If include_attic=True, data will include the complete history and also archived data.
    If include_privacy is set, it will include the privacy setting for contacts
    this user owns: private, restricted or public
    """
    result = None
    # do only enclose non-attic contacts unless attic parameter is set
    if contact.attic and not include_attic:
        return None

    result = ContactView(contact)

    if contact.class_name() == "Person":
        if contact.lastname:
            result.lastname = contact.lastname

    if login_user:
        # Birthday
        if contact.class_name() == "Person":
            if contact.birthday.has_year():
                result.birthyear = contact.birthday.year
            if contact.birthday.has_month():
                result.birthmonth = calendar.month_name[contact.birthday.month]
            if contact.birthday.has_day():
                result.birthday = contact.birthday.day

        # nickname
        if contact.nickname:
            result.nickname = contact.nickname

    # A user can see their own data, obviously
    if login_user and login_user.key() == contact.owned_by.key():
        # introduction/relation to this person
        result.relation = contact.introduction if contact.introduction else ""
        # Relation back to the middleman
        if contact.middleman_ref:
            result.middleman = contact.middleman_ref.name
            result.middleman_ref = str(contact.middleman_ref.key())

        # Relation(s) going out from this person towards others
        result.contacts = []
        # for con in Contact.all().filter("middleman_ref =", contact):
        for con in contact.affix:
            if not con.attic or include_attic:
                result.append_take2(con)

        # can I edit the contact data?
        if login_user:
            if contact.owned_by.key() == login_user.key():
                result.can_edit = True

        # Is this the contact data for the logged in user (myself)?
        if login_user and login_user.me:
            if contact.key() == login_user.me.key():
                result.is_myself = True

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
            if include_privacy:
                # look for an entry in the SharedTake2 table
                priv = SharedTake2.all().filter("contact_ref =", contact).filter("take2_ref =", obj).get()
                if priv:
                    if priv.class_name() == "PublicTake2":
                        # add privacy property to obj on the fly
                        obj.privacy = 'public'
                    elif priv.class_name() == "RestrictedTake2":
                        obj.privacy = 'restricted'
            result.append_take2(obj)
    else:
        # user does not own the contact, but let's check whether the privacy settings
        # allow us to see something
        q_priv = SharedTake2.all().filter("contact_ref =", contact)
        for priv in q_priv:
            # public objects
            if priv.class_name() == 'PublicTake2':
                obj = priv.take2_ref
                # do only enclose non-attic take2 properties unless attic parameter is set
                if obj.attic and not include_attic:
                    continue
                result.append_take2(obj)


    return result

