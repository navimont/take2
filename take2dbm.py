"""Take2 Database scheme"""

from google.appengine.ext import db
from google.appengine.ext.db import polymodel
from google.appengine.ext.db import BadValueError

class FuzzyDate(object):
    """A date which allows unknown day/month or year left out
    from: http://code.google.com/appengine/articles/extending_models.html
    """
    def __init__(self, year=0, month=0, day=0):
        self.year = year
        self.month = month
        self.day = day

    def has_day(self):
        return self.day > 0

    def has_month(self):
        return self.month > 0

    def has_year(self):
        return self.year > 0

    def __str__(self):
        return '%02d/%02d/%04d' % (self.day,self.month,self.year)

    def __not__(self):
        return (not(self.has_year() or
                self.has_month() or
                self.has_day()))

class FuzzyDateProperty(db.Property):

    # Tell what the user type is.
    data_type = FuzzyDate

    # For writing to datastore.
    def get_value_for_datastore(self, model_instance):
        date = super(FuzzyDateProperty,self).get_value_for_datastore(model_instance)
        return (date.month * 1000000) + (date.day * 10000) + date.year

    # For reading from datastore.
    def make_value_from_datastore(self, value):
        if value is None:
            return None
        return FuzzyDate(month=value / 1000000,
                         day=(value / 10000) % 100,
                         year=value % 10000)

    def validate(self, value):
        if value is not None and not isinstance(value, FuzzyDate):
            raise BadValueError('Property %s must be convertible '
                                'to a FuzzyDate instance (%s)' %
                                (self.name, value))
        return super(FuzzyDateProperty, self).validate(value)

    def default_value(self):
        return FuzzyDate(0,0,0)

    def empty(self, value):
        return not value


class Contact(polymodel.PolyModel):
    """Base class for person and Company"""
    # person's first name or name of a company
    name = db.StringProperty(required=True)

class Company(Contact):
    """Represents a company"""

class Person(Contact):
    """A natural Person"""
    nickname = db.StringProperty()
    lastname = db.StringProperty()
    birthday = FuzzyDateProperty()
    # a photo
    photo = db.BlobProperty()
    # where am I (right now)
    location = db.GeoPtProperty()
    # google login
    user = db.UserProperty()

class Country(db.Model):
    """Countries of the World"""
    name = db.StringProperty()

class Take2(polymodel.PolyModel):
    """Base class for a contac's properties.
    contact refers to the person/company
    """
    # Reference to a Person or a Company
    contact = db.ReferenceProperty(Contact, required=True)
    # creation timestamp
    timestamp = db.DateTimeProperty(auto_now=True)
    # how to treat this connection
    take2 = db.StringProperty(required=True, default="Restricted",
                                      choices=["Open",
                                       "Restricted",
                                       "Private",
                                       "Archived"])

class Link(Take2):
    """Links between Persons/Contacts
    This elements exists always twice for every link
    such as Bob can have another link to Alice as vice versa
    Bob ---'friend'---> Alice
    Alice ---'colleague'---> Bob
    """
    link = db.StringProperty(choices=["Sister","Brother","Father","Mother",
        "Son","Daughter","Parents","Friend","Employee","Colleague"])
    link_to = db.ReferenceProperty(Contact, required=True)

class Address(Take2):
    """Point of interest as was loaded from the OSM database"""
    # Coordinates for this Address
    location = db.GeoPtProperty()
    # Address
    adr = db.StringListProperty(required=True)
    landline_phone = db.PhoneNumberProperty()
    country = db.ReferenceProperty(Country)

class Mobile(Take2):
    # mobile number
    mobile = db.PhoneNumberProperty(required=True)

class Web(Take2):
    # web address
    web = db.LinkProperty(required=True)

class Email(Take2):
    # email
    email = db.EmailProperty()

class Note(Take2):
    # note
    note = db.TextProperty()

class Other(Take2):
    """Any other information"""
    what = db.StringProperty(choices=[])
    text = db.StringProperty()
