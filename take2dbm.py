"""Take2 Database scheme"""

import geo.geomodel
from google.appengine.ext import db
from google.appengine.ext.db import polymodel

class Contact(polymodel.PolyModel)
    """Base class for person and Company"""
    # person's first name or name of a company
    name = db.StringProperty(required=True)

class Company(Contact)
    """Represents a company"""

class Person(Contact):
    """A natural Person"""
    nickname = db.StringProperty()
    lastname = db.StringProperty()
    birthday = db.DateProperty()
    # a photo
    photo = db.BlobProperty()
    # where am I (right now)
    location = db.GeoPtProperty()
    # google login
    user = db.UserProperty()

class Country(db.Model)
    """Countries of the World"""
    name = db.StringProperty()

class Take2(polymodel.PolyModel)
    """Base class for a contac's properties.
    contact refers to the person/company
    """
    # Reference to a Person or a Company
    contact = db.ReferenceProperty(Contact, required=True)
    # creation timestamp
    timestamp = db.DateTimeProperty(required=True)
    # how to treat this connection
    attic = db.StringProperty(required=True, choices=["Open",
                                       "Restricted",
                                       "Private",
                                       "Archived"])

class Link(Take2)
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

class Mobile(Take2)
    # mobile number
    mobile = db.PhoneNumberProperty(required=True)

class Web(Take2)
    # web address
    web = db.LinkProperty(required=True)

class Email(Take2)
    # email
    email = emailProperty()

class Note(Take2)
    # note
    note = db.TextProperty()

class Other(Take2)
    """Any other information"""
    type = db.StringProperty(choices=)
