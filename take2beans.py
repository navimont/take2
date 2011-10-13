"""Bean classes representing the business objects handled by the RequestHandlers


    Stefan Wehner (2011)
"""

import settings
import logging
import calendar
from datetime import datetime
from django.core.validators import validate_email, URLValidator
from django.core.exceptions import ValidationError
from google.appengine.ext import db
from take2dbm import Contact, Person, Take2, FuzzyDate
from take2dbm import Email, Address, Mobile, Web, Other, OtherTag
from take2index import update_index


def prepare_list_of_other_tags():
    """prepares a list of previously used tags in a  data structure ready for the template use"""
    taglist = []
    for tag in OtherTag.all():
        taglist.append(tag.tag)
    return taglist

def prepare_birthday_selectors():
    """Prepare the lists of days and month which are needed to enter a valid birthday"""

    # prepare list of days and months
    daylist = ["(skip)"]
    daylist.extend([str(day) for day in range(1,32)])
    monthlist=[(str(i),calendar.month_name[i]) for i in range(13)]
    monthlist[0] = ("0","(skip)")
    yearlist = ["(skip)"]
    yearlist.extend([str(year) for year in range(datetime.today().year,datetime.today().year-120,-1)])

    return {'daylist': daylist, 'monthlist': monthlist, 'yearlist': yearlist}


class EntityBean(object):
    def __init__(self,owned_by):
        self.owned_by = owned_by
        self.entity = None
        self.template_values = {}

    def get_template_values(self):
        if self.entity:
            self.template_values['%s_key' % self.entity.class_name()] = str(self.entity.key())

    def get_entity(self):
        """Returns the database representation"""
        return self.entity

    def validate(self):
        return []


class ContactBean(EntityBean):
    def __init__(self,owned_by):
        super(ContactBean,self).__init__(owned_by)


class PersonBean(ContactBean):
    @classmethod
    def new_person(cls, owned_by):
        """factory method for a new person bean"""
        return PersonBean(owned_by,None)

    @classmethod
    def load(cls, key):
        entity = Person.get(key)
        person = PersonBean(entity.owned_by,None)
        person.entity = entity
        person.name = entity.name
        person.nickname = entity.nickname
        person.lastname = entity.lastname
        person.birthday = entity.birthday
        person.introduction = entity.introduction
        if entity.middleman_ref:
            person.middleman_ref = str(entity.middleman_ref.key())
        return person

    @classmethod
    def edit(cls, owned_by, request):
        """factory method for a new person bean"""
        person = PersonBean(owned_by,None)
        if request.get('Person_key', None):
            person.entity = Person.get(request.get('Person_key'))
        person.name = request.get('name')
        person.nickname = request.get('nickname',"")
        person.lastname = request.get('lastname',"")
        person.introduction = request.get('introduction',"")
        person.middleman_ref = request.get('middleman_ref',None)
        try:
            birthday = int(request.get("birthday", None))
        except ValueError:
            birthday = 0
        except TypeError:
            birthday = 0
        try:
            birthmonth = int(request.get("birthmonth", None))
        except ValueError:
            birthmonth = 0
        except TypeError:
            birthmonth = 0
        try:
            birthyear = int(request.get("birthyear", None))
        except ValueError:
            birthyear = 0
        except TypeError:
            birthyear = 0
        person.birthday = FuzzyDate(day=birthday,month=birthmonth,year=birthyear)
        return person

    @classmethod
    def new_person_via_middleman(cls, owned_by, middleman_ref):
        """factory method for a new person wirth middleman bean"""
        return PersonBean(owned_by,middleman_ref)

    def __init__(self, owned_by, middleman_ref=None):
        super(PersonBean,self).__init__(owned_by)
        if middleman_ref:
            self.middleman_ref = middleman_ref
        else:
            self.middleman_ref = None
        self.name = ""
        self.nickname = ""
        self.lastname = ""
        self.introduction = ""
        self.parent = None
        self.birthday = FuzzyDate(year=0,month=0,day=0)

    def validate(self):
        if len(self.name) < 1:
            return ['Name is required']
        return []

    def get_template_values(self):
        """return person data as template_values"""
        super(PersonBean,self).get_template_values()
        self.template_values.update(prepare_birthday_selectors())
        if self.middleman_ref:
            self.template_values['middleman_ref'] = self.middleman_ref
            # look him up to fill the fields
            middleman = Person.get(db.Key(self.middleman_ref))
            if middleman:
                self.template_values['middleman_name'] = middleman.name
                self.template_values['middleman_lastname'] = middleman.lastname
        self.template_values['name'] = self.name
        self.template_values['nickname'] = self.nickname
        self.template_values['lastname'] = self.lastname
        self.template_values['introduction'] = self.introduction
        self.template_values['birthday'] = str(self.birthday.get_day())
        self.template_values['birthmonth'] = str(self.birthday.get_month())
        self.template_values['birthyear'] = str(self.birthday.get_year())
        return self.template_values

    def put(self):
        if self.middleman_ref:
            middleman = db.Key(self.middleman_ref)
        else:
            middleman = None
        try:
            self.entity.name = self.name
            self.entity.nickname = self.nickname
            self.entity.lastname = self.lastname
            self.entity.introduction = self.introduction
            self.entity.birthday = self.birthday
            self.entity.middleman_ref = middleman
            # parent is needed for building an entity group with LoginUser
            self.entity.parent = self.parent
            self.entity.put()
        except AttributeError:
            # prepare database object for new person
            self.entity = Person(parent=self.parent, owned_by=self.owned_by, name=self.name,
                                lastname=self.lastname,
                                nickname=self.nickname, birthday=self.birthday,
                                introduction=self.introduction, middleman_ref=middleman)
            self.entity.put()
        if not self.parent:
            # generate search keys for contact; cannot run in transaction context
            update_index(self.entity)


class Take2Bean(EntityBean):
    def __init__(self,contact_ref):
        self.contact_ref = contact_ref
        self.entity = None
        self.template_values = {}


class EmailBean(Take2Bean):
    @classmethod
    def new(cls,contact_ref):
        return EmailBean(contact_ref)

    @classmethod
    def load(cls, key):
        entity = Email.get(key)
        email = EmailBean(entity.contact_ref)
        email.entity = entity
        email.email = entity.email
        return email

    @classmethod
    def edit(cls,contact_ref,request):
        email = EmailBean(contact_ref)
        if request.get('Email_key', None):
            email.entity = Email.get(request.get('Email_key'))
        email.email = request.get('email')
        return email

    def __init__(self,contact_ref):
        super(EmailBean,self).__init__(contact_ref)
        self.email = ""

    def get_template_values(self):
        super(EmailBean,self).get_template_values()
        self.template_values['email'] = self.email
        return self.template_values

    def validate(self):
        try:
            validate_email(self.email)
        except ValidationError:
            return ['Invalid email address']
        return []

    def put(self):
        try:
            self.entity.email = self.email
            self.entity.put()
        except AttributeError:
            self.entity = Email(contact_ref=self.contact_ref, email=self.email)
            self.entity.put()


class MobileBean(Take2Bean):
    @classmethod
    def new(cls,contact_ref):
        return MobileBean(contact_ref)

    @classmethod
    def load(cls, key):
        entity = Mobile.get(key)
        mobile = MobileBean(entity.contact_ref)
        mobile.entity = entity
        mobile.mobile = entity.mobile
        return mobile

    @classmethod
    def edit(cls,contact_ref,request):
        key = request.get('Mobile_key', None)
        if key:
            mobile = cls.load(key)
        else:
            mobile = MobileBean(contact_ref)
        mobile.mobile = request.get('mobile')
        return mobile

    def __init__(self,contact_ref):
        super(MobileBean,self).__init__(contact_ref)
        self.mobile = ""

    def validate(self):
        if len(self.mobile) < 3:
            return ['Mobile number too short']
        return []

    def get_template_values(self):
        super(MobileBean,self).get_template_values()
        self.template_values['mobile'] = self.mobile
        return self.template_values

    def put(self):
        try:
            self.entity.mobile = self.mobile
            self.entity.put()
        except AttributeError:
            # prepare database object for new person
            self.entity = Mobile(contact_ref=self.contact_ref, mobile=self.mobile)
            self.entity.put()


class WebBean(Take2Bean):
    @classmethod
    def new(cls,contact_ref):
        return WebBean(contact_ref)

    @classmethod
    def load(cls, key):
        entity = Web.get(key)
        web = WebBean(entity.contact_ref)
        web.entity = entity
        web.web = entity.web
        return web

    @classmethod
    def edit(cls,contact_ref,request):
        key = request.get('Web_key', None)
        if key:
            web = cls.load(key)
        else:
            web = WebBean(contact_ref)
        web.web = request.get('web')
        return web

    def __init__(self,contact_ref):
        super(WebBean,self).__init__(contact_ref)
        self.web = ""

    def validate(self):
      validate = URLValidator(verify_exists=True)
      try:
          validate(self.web)
      except ValidationError:
        return ['Invalid web address']

    def get_template_values(self):
        super(WebBean,self).get_template_values()
        self.template_values['web'] = self.web
        return self.template_values

    def put(self):
        try:
            self.entity.web = self.web
            self.entity.put()
        except AttributeError:
            # prepare database object for new person
            self.entity = Web(contact_ref=self.contact_ref, web=self.web)
            self.entity.put()


class OtherBean(Take2Bean):
    @classmethod
    def new(cls,contact_ref):
        return OtherBean(contact_ref)

    @classmethod
    def load(cls, key):
        entity = Other.get(key)
        other = OtherBean(entity.contact_ref)
        other.entity = entity
        other.text = entity.text
        if entity.tag:
            other.tag = entity.tag.tag
        return other

    @classmethod
    def edit(cls,contact_ref,request):
        key = request.get('Other_key', None)
        if key:
            other = cls.load(key)
        else:
            other = OtherBean(contact_ref)
        other.text = request.get('text')
        other.tag = request.get('tag')
        return other

    def __init__(self,contact_ref):
        super(OtherBean,self).__init__(contact_ref)
        self.text = ""
        self.tag = ""

    def validate(self):
        return []

    def get_template_values(self):
        super(OtherBean,self).get_template_values()
        self.template_values['text'] = self.text
        self.template_values['tag'] = self.tag
        self.template_values['taglist'] = prepare_list_of_other_tags()
        return self.template_values

    def put(self):
        if len(self.tag) > 0:
            tag = OtherTag.all().filter("tag =", self.tag).get()
            # If tag name is not in DB it is added
            if not tag:
                tag = OtherTag(tag=self.tag)
                tag.put()
        else:
            tag = None
        try:
            self.entity.tag = tag
            self.entity.text = self.text
            self.entity.put()
        except AttributeError:
            # prepare database object for new person
            self.entity = Other(contact_ref=self.contact_ref, text=self.text, tag=tag)
            self.entity.put()


class AddressBean(Take2Bean):
    @classmethod
    def new(cls,contact_ref):
        return AddressBean(contact_ref)

    @classmethod
    def load(cls, key):
        entity = Address.get(key)
        address = AddressBean(entity.contact_ref)
        address.entity = entity
        # properties follow
        address.adr = entity.adr
        address.landline_phone = entity.landline_phone
        address.location_lock = entity.location_lock
        address.lon = entity.location.lon
        address.lat = entity.location.lat
        address.map_zoom = entity.map_zoom
        address.adr_zoom = entity.adr_zoom
        return address

    @classmethod
    def edit(cls,contact_ref,request):
        key = request.get('Address_key', None)
        if key:
            address = cls.load(key)
        else:
            address = AddressBean(contact_ref)
        # properties follow
        address.adr = request.get('adr', "").split("\n")
        address.landline_phone = request.get('landline_phone', "")
        address.location_lock = True if request.get('location_lock', None) else False
        lat_raw = request.get("lat", "")
        address.lat = 0.0 if len(lat_raw) == 0 else float(lat_raw)
        lon_raw = request.get("lon", "")
        address.lon = 0.0 if len(lon_raw) == 0 else float(lon_raw)
        address.map_zoom = int(request.get('map_zoom', "8"))
        address.adr_zoom = [line.strip() for line in request.get("adr_zoom", "").split(",")]
        return address

    def __init__(self,contact_ref):
        super(AddressBean,self).__init__(contact_ref)
        # properties follow
        self.adr = []
        self.landline_phone = ""
        self.location_lock = False
        self.lon = 0.0
        self.lat = 0.0
        self.map_zoom = 8
        self.adr_zoom = []

    def validate(self):
        adr = "".join(self.adr)
        if len(adr) < 3 and self.lat == 0.0 and self.lon == 0.0:
            return ['Please enter an address']

    def get_template_values(self):
        super(AddressBean,self).get_template_values()
        # properties follow
        self.template_values['adr'] = "\n".join(self.adr)
        self.template_values['landline_phone'] = self.landline_phone
        self.template_values['lat'] = self.lat
        self.template_values['lon'] = self.lon
        self.template_values['location_lock'] = self.location_lock
        self.template_values['map_zoom'] = str(self.map_zoom)
        if self.adr_zoom:
            self.template_values['adr_zoom'] = ", ".join(self.adr_zoom)
        return self.template_values

    def put(self):
        try:
            self.entity.adr = self.adr
            self.entity.landline_phone = self.landline_phone
            self.entity.location = location=db.GeoPt(lon=self.lon, lat=self.lat)
            self.entity.location_lock = self.location_lock
            self.entity.map_zoom = self.map_zoom
            self.entity.adr_zoom = self.adr_zoom
            self.entity.put()
        except AttributeError:
            # prepare database object for new person
            self.entity = Address(contact_ref=self.contact_ref, adr=self.adr,
                                  landline_phone=self.landline_phone,
                                  location=db.GeoPt(lon=self.lon, lat=self.lat), location_lock=self.location_lock,
                                  map_zoom=self.map_zoom, adr_zoom=self.adr_zoom)
            self.entity.put()
        update_index(self.entity)


def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)

if __name__ == "__main__":
    main()
