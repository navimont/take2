"""Bean classes representing the business objects handled by the RequestHandlers"""

import settings
import logging
from take2dbm import Contact, Person, Take2, FuzzyDate
from take2dbm import Email, Address, Mobile, Web, Other, Country, OtherTag
from take2index import check_and_store_key
import calendar
from datetime import datetime
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

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
            template_values['%s_key' % self.entity.class_name()] = str(self.entity.key())

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
    def edit(cls, owned_by, request):
        """factory method for a new person bean"""
        person = PersonBean(owned_by,None)
        if request.get('Person_key', None):
            person.entity = Person.get(request.get('Person_key'))
        person.name = request.get('name')
        person.nickname = request.get('nickname',"")
        person.lastname = request.get('lastname',"")
        person.introduction = request.get('introduction',"")
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
    def new_person_via_middleman(cls, owned_by, middleman):
        """factory method for a new person wirth middleman bean"""
        return PersonBean(owned_by,middleman)

    def __init__(self,owned_by,middleman_ref=None):
        super(PersonBean,self).__init__(owned_by)
        if middleman_ref:
            # read middleman Person entry from DB
            self.middleman = Person.get(middleman_ref)
        else:
            self.middleman = None
        self.name = ""
        self.nickname = ""
        self.lastname = ""
        self.introduction = ""
        self.birthday = FuzzyDate(year=0,month=0,day=0)

    def validate(self):
        # throws ValidationError
        if len(self.name) < 1:
            return ['Invalid name']
        return []

    def get_template_values(self):
        """return person data as template_values"""
        super(PersonBean,self).get_template_values()
        self.template_values.update(prepare_birthday_selectors())
        if self.middleman:
            self.template_values['middleman_ref'] = str(self.middleman.key())
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
        try:
            self.entity.name = self.name
            self.entity.nickname = self.nickname
            self.entity.lastname = self.lastname
            self.entity.introduction = self.introduction
            self.entity.birthday = self.birthday
            self.entity.put()
        except AttributeError:
            # prepare database object for new person
            self.entity = Person(owned_by=self.owned_by, name=self.name, lastname=self.lastname,
                                 nickname=self.nickname, birthday=self.birthday, introduction=self.introduction)
            self.entity.put()
        # generate search keys for contact
        check_and_store_key(self.entity)


class Take2Bean(EntityBean):
    def __init__(self,owned_by,contact_ref):
        super(Take2Bean,self).__init__(owned_by)
        self.contact_ref = contact_ref


class EmailBean(Take2Bean):
    @classmethod
    def new(cls,owned_by,contact_ref):
        return EmailBean(owned_by,contact_ref)

    @classmethod
    def edit(cls,owned_by,contact_ref,request):
        email = EmailBean(owned_by,contact_ref)
        if request.get('Email_key', None):
            email.entity = Email.get(request.get('Email_key'))
        email.email = request.get('email')
        return email

    def __init__(self,owned_by,contact_ref):
        super(EmailBean,self).__init__(owned_by,contact_ref)
        self.email = ""

    def get_template_values(self):
        super(EmailBean,self).get_template_values()
        self.template_values['email'] = self.email
        return self.template_values

    def validate(self):
        # throws ValidationError
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
            # prepare database object for new person
            self.entity = Email(owned_by=self.owned_by, contact_ref=self.contact_ref, email=self.email)
            self.entity.put()
        # generate search keys for contact
        check_and_store_key(self.entity)



class MobileBean(Take2Bean):
    @classmethod
    def new(cls,owned_by,contact_ref):
        return MobileBean(owned_by,contact_ref)

    @classmethod
    def edit(cls,owned_by,contact_ref,request):
        mobile = MobileBean(owned_by,contact_ref)
        if request.get('Mobile_key', None):
            email.entity = Mobile.get(request.get('Mobile_key'))
        mobile.mobile = request.get('mobile')
        return mobile

    def __init__(self,owned_by,contact_ref):
        super(MobileBean,self).__init__(owned_by,contact_ref)
        self.mobile = ""

    def validate(self):
        # throws ValidationError
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
            self.mobile_db.put()
        except AttributeError:
            # prepare database object for new person
            self.mobile_db = Mobile(owned_by=self.owned_by, contact_ref=self.contact_ref, mobile=self.mobile)
            self.mobile_db.put()
        # generate search keys for contact
        check_and_store_key(self.mobile_db)


def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)

if __name__ == "__main__":
    main()
