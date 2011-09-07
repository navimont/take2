"""Take2 Database scheme"""

from google.appengine.ext import db
from google.appengine.ext.db import polymodel
from google.appengine.ext.db import BadValueError
import settings

class FuzzyDate(object):
    """A date which allows unknown day/month or year left out
    from: http://code.google.com/appengine/articles/extending_models.html
    """
    def __init__(self, year=0, month=0, day=0, ddmmyyyy=None):
        """Use constructor wither with tea, month day given
        (or set to 0) or by assigning ddmmyyyy coded integer"""
        if ddmmyyyy:
            self.day = ddmmyyyy / 1000000
            self.month = (ddmmyyyy / 10000) % 100
            self.year = ddmmyyyy % 10000
        else:
            self.year = year
            self.month = month
            self.day = day


    def to_ddmmyyy(self):
        """return date as a ddmmyyyy coded integer
        for use in FuzzyDateProperty class"""
        return (self.day * 1000000) + (self.month * 10000) + self.year

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

    # For writing to datastore. Date is stored as
    # integer mmddyyyy
    def get_value_for_datastore(self, model_instance):
        date = super(FuzzyDateProperty,self).get_value_for_datastore(model_instance)
        # return (date.day * 1000000) + (date.month * 10000) + date.year
        return date.to_ddmmyyy()

    # For reading from datastore.
    def make_value_from_datastore(self, value):
        if value is None:
            return None
        return FuzzyDate(ddmmyyyy=value)

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
    # archived
    attic = db.BooleanProperty(default=False)
    # points to the Person instance who owns (created)
    # an instance. May point to itself.
    owned_by = db.SelfReferenceProperty()


class Company(Contact):
    """Represents a company"""

class Person(Contact):
    """A natural Person"""
    lastname = db.StringProperty()
    birthday = FuzzyDateProperty(default=FuzzyDate(0,0,0))
    # a photo
    photo = db.BlobProperty()
    # where am I (right now)
    location = db.GeoPtProperty()
    # google login
    user = db.UserProperty()

class Take2(polymodel.PolyModel):
    """Base class for a contact's data.
    A history of data is stored by never updating
    a Take2 derived data class. Instead, when data is
    updated, a new instance is created. The last
    entity points to he contact. The one which was just
    replaced, points to the new data entity.
    """
    # Reference to a Person or a Company or to a
    # newer version of this entity.
    contact = db.ReferenceProperty(reference_class=None, required=True)
    # creation timestamp
    timestamp = db.DateTimeProperty(auto_now=True)
    # how to treat this connection
    privacy = db.StringProperty(required=True, default="Restricted",
                                      choices=["Open",
                                       "Restricted",
                                       "Private"])
    # archived
    attic = db.BooleanProperty(default=False)

class Link(Take2):
    """Links between Persons/Contacts
    This elements exists always twice for every link
    such as Bob can have another link to Alice as vice versa
    Bob ---'friend'---> Alice
    Alice ---'colleague'---> Bob
    """
    nickname = db.StringProperty()
    link = db.StringProperty(choices=settings.PERSON_RELATIONS+settings.INSTITUTION_RELATIONS)
    link_to = db.ReferenceProperty(Contact, required=True)

class Address(Take2):
    """Point of interest as was loaded from the OSM database"""
    # Coordinates for this Address
    location = db.GeoPtProperty()
    # Address
    adr = db.StringListProperty(required=True)
    landline_phone = db.PhoneNumberProperty(required=False)
    country = db.StringProperty(required=True, choices=[c.values()[0] for c in settings.COUNTRIES])

class Mobile(Take2):
    # mobile number
    mobile = db.PhoneNumberProperty(required=True)

class Web(Take2):
    # web address
    web = db.LinkProperty(required=True)

class Email(Take2):
    # email
    email = db.EmailProperty()

class Other(Take2):
    """Any other information"""
    what = db.StringProperty(choices=settings.OTHER_TAGS)
    text = db.StringProperty()
