"""Take2 Database scheme


  Stefan Wehner (2011)
"""

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

class LoginUser(db.Model):
    """A user instance (connects with one google account)

    It supports geospatial queries with the help of GeoModel
    Call update_location() method before storing location changes.
    """
    # user data as returned by users.get_current_user()
    user = db.UserProperty()
    # a duplicate, I do save user.federated_identity to this
    # field because a query with a yahoo identity fails on user
    user_id = db.StringProperty()
    # store user's current location (from browser geolookup)
    location = db.GeoPtProperty()
    location_timestamp = db.DateTimeProperty()
    # the last known place (looked up from location coordinates)
    place = db.StringProperty()
    # points to the Person which represents this user
    # (can't use the Person qualifier because Person is not defined yet)
    me = db.ReferenceProperty()
    #
    # Settings
    #
    # ask user for her location not before this date!
    ask_geolocation = db.DateTimeProperty()

class Contact(polymodel.PolyModel):
    """Base class for person and Company"""
    # person's first name or name of a company
    name = db.StringProperty(required=True)
    # archived
    attic = db.BooleanProperty(default=False)
    # creation timestamp
    timestamp = db.DateTimeProperty(auto_now=True)
    # points to the User instance who owns (created) the instance.
    owned_by = db.ReferenceProperty(LoginUser)
    # a line about who this person is
    introduction = db.StringProperty()
    # This contact might be related to another person. If so, 'introduction'
    # describes the kind of the relation and middleman_ref points to the person.
    # As an example, Jose is my friend and Nelly is his wife. There need not
    # to be a middleman_ref from Jose to me (as I know him well) but Nelly may
    # just appear in my address book because she's his wife rather than
    # having a relation to me.
    # introduction="My friend Jose's wife"
    # [Nelly].middleman_ref --> [Jose]
    middleman_ref = db.ReferenceProperty(collection_name='affix')

class Company(Contact):
    """Represents a company"""

class Person(Contact):
    """A natural Person"""
    lastname = db.StringProperty()
    nickname = db.StringProperty()
    birthday = FuzzyDateProperty(default=FuzzyDate(0,0,0))

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
    timestamp = db.DateTimeProperty(auto_now=True)
    # archived
    attic = db.BooleanProperty(default=False)

class Country(db.Model):
    """List of countries of the world"""
    ccode = db.StringProperty()
    country = db.StringProperty(required=True)

class Address(Take2):
    """Point of interest as was loaded from the OSM database"""
    # Coordinates for this Address
    location = db.GeoPtProperty()
    # an appropriate zoom level to view the address on a map
    map_zoom = db.IntegerProperty()
    # set to true if coordinates shall not be overwritten by geocoding lookup
    location_lock = db.BooleanProperty(default=False)
    # Address
    adr = db.StringListProperty(required=True)
    landline_phone = db.StringProperty(required=False)
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
    # tags are private to users
    owned_by = db.ReferenceProperty(LoginUser)

class Other(Take2):
    """Any other information"""
    tag = db.ReferenceProperty(OtherTag)
    # content
    text = db.StringProperty()

class SearchIndex(db.Model):
    """Combined index for efficient search in

    - name       (name: Contact)
    - nickname   (nickname: Person)
    - last name  (lastname: Person)
    - place      (adr_zoom: Address)
    """
    # a plainified version of the words in the original string
    # (all lower case, ASCII only)
    keys = db.StringListProperty()
    # True if entry is marked deleted
    attic = db.BooleanProperty()
    # points to the dataset from where the data originates
    # can be any of Contact, Take2 and their descendants
    data_ref = db.ReferenceProperty()
    # pointer to contact
    contact_ref = db.ReferenceProperty(Contact)

class GeoIndex(GeoModel):
    """Indexes the location fields in LoginUser and Address datasets
    for a quick location based search (supported by parent class)
    """

    # location property is defined in parent class
    # location = db.GeoPtProperty(required=True)
    # location_geocells is defined in parent class and used for quick geo queries
    # location_geocells = db.StringListProperty()
    # needs to be updated before every put. Call update_location() on the class

    # True if entry is marked deleted
    attic = db.BooleanProperty()
    # points to the dataset from where the data originates
    # can be any of Contact, Take2 and their descendants
    data_ref = db.ReferenceProperty()
    # pointer to contact
    contact_ref = db.ReferenceProperty(Contact)


class SharedTake2(polymodel.PolyModel):
    """Holds a list of take2 properties which may be seen by the public or friends"""
    contact_ref = db.ReferenceProperty(Contact)
    take2_ref = db.ReferenceProperty(Take2)

class PublicTake2(SharedTake2):
    """Holds a list of take2 properties which may be seen by the public"""

class RestrictedTake2(SharedTake2):
    """Holds a list of take2 properties which may be seen by friends"""


