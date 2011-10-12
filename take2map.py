"""Take2 buld quick search index to find a contact by its name, location, nickname etc.

    Stefan Wehner (2011)

"""

import settings
import logging
import os
from django.utils import simplejson as json
import unicodedata
from random import shuffle
from datetime import datetime
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import memcache
from take2dbm import Contact, Person, Company, Take2, SearchIndex, Address
from take2access import get_login_user, get_current_user_template_values
from take2index import lookup_contacts
from take2view import geocode_contact


class Map(webapp.RequestHandler):
    """"""

    def get(self):
        login_user = get_login_user()
        template_values = get_current_user_template_values(login_user,self.request.uri)

        path = os.path.join(os.path.dirname(__file__), 'take2map.html')
        self.response.out.write(template.render(path, template_values))

class MapPopulate(webapp.RequestHandler):
    """Returns lust of users in the bounding box specified by get parameters"""

    def get(self):
        login_user = get_login_user()
        # bbox is in GeoJson notation [minlon,minlat,maxlon,maxlat]
        bbox = self.request.get('bbox',"0,0,0,0").split(',')
        minlat = float(bbox[1])
        minlon = float(bbox[0])
        maxlat = float(bbox[3])
        maxlon = float(bbox[2])

        geojson = {"type": "FeatureCollection"}
        geojson['features'] = []

        geojson["bbox"] = bbox

        # encode and return
        # self.response.headers['Content-Type'] = "application/json"
        self.response.headers['Content-Type'] = "text/plain"
        self.response.out.write(json.dumps(geojson))


class MapData(webapp.RequestHandler):
    """Handler for ajax request. Returns list of geocoded names"""

    def get(self):
        login_user = get_login_user()
        query = self.request.get('query',"")
        include_attic = True if self.request.get('attic',None) else False

        # data structures for data transport to client
        nongeo = []
        geojson = []
        geojson = {"type": "FeatureCollection"}
        geojson['features'] = []

        minlat = 0.0
        maxlat = 0.0
        minlon = 0.0
        maxlon = 0.0

        logging.debug(query)
        if query:
            cis = lookup_contacts(query, include_attic)
            # Save the query result in memcache together with the information about
            # which portion of it we are displaying (the first result_size datasets as
            # it is a fresh query!)
            if login_user:
                if not memcache.set('query', {'query': query, 'offset': 0, 'results': cis}, time=5000, namespace=str(login_user.key())):
                    logging.error("memcache failed")
            # fetch a number of data from the results
            for contact in db.get(cis[0:settings.RESULT_SIZE]):
                if not contact:
                    # may happen if index is not up to date
                    logging.warning("Query returned invalid contact reference")
                    continue
                try:
                    con = geocode_contact(contact, include_attic=include_attic, login_user=login_user)
                    if con:
                        # geoconding successful
                        geojson['features'].extend(con)
                    else:
                        nongeo.append(encode_contact(contact_ref, login_user, include_attic=False))
                except db.ReferencePropertyResolveError:
                    logging.critical("AttributeError while encoding")


        # calculate bounding box (viewport)
        for feature in geojson['features']:
            coords = feature['geometry']['coordinates']
            if coords[0] != 0.0 and coords[1] != 0.0:
                # initialize to first point
                if minlon == 0.0:
                    minlon = coords[0]
                    maxlon = coords[0]
                if coords[0] > maxlon:
                    maxlon = coords[0]
                if coords[0] < minlon:
                    minlon = coords[0]
                if minlat == 0.0:
                    minlat = coords[1]
                    maxlat = coords[1]
                if coords[1] > maxlat:
                    maxlat = coords[1]
                if coords[1] < minlat:
                    minlat = coords[1]
        geojson["bbox"] = [minlon,minlat,maxlon,maxlat]

        # encode and return
        # self.response.headers['Content-Type'] = "application/json"
        self.response.headers['Content-Type'] = "text/plain"
        self.response.out.write(json.dumps(geojson, indent= 2 if settings.DEBUG else 0))


application = webapp.WSGIApplication([('/map', Map),
                                      ('/mapdata', MapData),
                                      ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

