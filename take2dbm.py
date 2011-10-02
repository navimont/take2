"""Take2 Database scheme"""

from google.appengine.ext import db
from google.appengine.ext.db import polymodel
from google.appengine.ext.db import BadValueError
from geo.geomodel import GeoModel
import settings

class FuzzyDate(object):
    """A date which allows unknown day/month or year left out
    from: http://code.google.com/appengine/articles/extending_models.html
    """
    def __init__(self, year=0, month=0, day=0, mmddyyyy=None):
        """Use constructor wither with tea, month day given
        (or set to 0) or by assigning mmddyyyy coded integer"""
        if mmddyyyy:
            self.month = mmddyyyy / 1000000
            self.day = (mmddyyyy / 10000) % 100
            self.year = mmddyyyy % 10000
        else:
            self.year = year
            self.month = month
            self.day = day


    def to_int(self):
        """return date as a coded integer
        for use in FuzzyDateProperty class"""
        return (self.month * 1000000) + (self.day * 10000) + self.year

    def has_day(self):
        return self.day > 0

    def has_month(self):
        return self.month > 0

    def has_year(self):
        return self.year > 0

    def get_day(self):
        return self.day

    def get_month(self):
        return self.month

    def get_year(self):
        return self.year

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
        return date.to_int()

    # For reading from datastore.
    def make_value_from_datastore(self, value):
        if value is None:
            return None
        return FuzzyDate(mmddyyyy=value)

    def validate(self, value):
        if value is not None and not isinstance(value, FuzzyDate):
            raise BadValueError('Property %s must be a FuzzyDate instance (%s)' % (self.name, value))
        # call base class validate
        return super(FuzzyDateProperty, self).validate(value)

    def default_value(self):
        return FuzzyDate(0,0,0)

    def empty(self, value):
        return not value

class LoginUser(GeoModel):
    """A user instance (connects with one google account)

    It supports geospatial queries with the help of GeoModel
    Call update_location() method before storing location changes.
    """
    # google login
    user = db.UserProperty()
    # location attribute comes from parent class and is required
    location_timestamp = db.DateTimeProperty(auto_now=True)
    # points to the Person which represents this user
    # (can't use the Person qualifier because Person is not defined yet)
    me = db.ReferenceProperty()

class Contact(polymodel.PolyModel):
    """Base class for person and Company"""
    # person's first name or name of a company
    name = db.StringProperty(required=True)
    # archived
    attic = db.BooleanProperty(default=False)
    # creation timestamp
    timestamp = db.DateTimeProperty(auto_now_add=True)
    # points to the User instance who owns (created) the instance.
    owned_by = db.ReferenceProperty(LoginUser)

class Company(Contact):
    """Represents a company"""

class Person(Contact):
    """A natural Person"""
    lastname = db.StringProperty()
    nickname = db.StringProperty()
    birthday = FuzzyDateProperty(default=FuzzyDate(0,0,0))
    # This person might be related to another person. If so, 'relation'
    # describes the kind of the relation and back_ref points to the person.
    # as an example, Jose is my friend and Nelly is his wife. There need not
    # to be a back_ref from Jose to me (as I know him well) but Nelly may
    # just appear in my address book because she's his wife rather than
    # having a relation to me.
    # So relation="My friend Jose's wife"
    # [Nelly].back_ref --> [Jose]
    relation = db.StringProperty()
    back_ref = db.ReferenceProperty()
    # a photo
    photo = db.BlobProperty()

class Take2(polymodel.PolyModel):
    """Base class for a contact's data.
    A history of data is stored by never updating
    a Take2 derived data class. Instead, when data is
    updated, a new instance is created. The latest
    entity points to the contact. The one which was just
    replaced, points to the newly created take2 instance.
    """
    # Reference to a Person or a Company or to a
    # newer version of this entity.
    contact_ref = db.ReferenceProperty(reference_class=None, required=True)
    # creation timestamp
    timestamp = db.DateTimeProperty(auto_now_add=True)
    # archived
    attic = db.BooleanProperty(default=False)

class Link(Take2):
    """Links between Persons/Contacts
    """

class Country(db.Model):
    """List of countries of the world"""
    ccode = db.StringProperty()
    country = db.StringProperty(required=True)

class Address(Take2):
    """Point of interest as was loaded from the OSM database"""
    # Coordinates for this Address
    location = db.GeoPtProperty()
    # Address
    adr = db.StringListProperty(required=True)
    landline_phone = db.PhoneNumberProperty(required=False)
    country = db.ReferenceProperty(Country)
    # those are filled by the address lookup (geocoding)
    # and contain items like: [earth,USA,NY,Brooklyn,Fort Greene]
    adr_zoom = db.StringListProperty()

class Mobile(Take2):
    # mobile number
    mobile = db.PhoneNumberProperty(required=True)

class Web(Take2):
    # web address
    web = db.LinkProperty(required=True)

class Email(Take2):
    # email
    email = db.EmailProperty()

class OtherTag(db.Model):
    """Describes the content of the other text field"""
    # description
    tag = db.StringProperty()

class Other(Take2):
    """Any other information"""
    tag = db.ReferenceProperty(OtherTag)
    # content
    text = db.StringProperty()

class PlainKey(db.Model):
    """An index for quick search in names, last names, nicknames and places

    Entries in this index are all lower case and they do not accents or special
    characters.
    """
    plain_key = db.StringProperty()

class ContactIndex(db.Model):
    """Is used to connect entries in the Lookup class with Person or Company entities"""

    plain_key_ref = db.ReferenceProperty(PlainKey)
    contact_ref = db.ReferenceProperty(Contact)


