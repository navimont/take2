"""Take2 buld quick search index to find a contact by its name, location, nickname etc.

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


class Map(webapp.RequestHandler):
    """"""

    def get(self):
        login_user = get_login_user()
        template_values = get_current_user_template_values(login_user,self.request.uri)

        path = os.path.join(os.path.dirname(__file__), 'take2map.html')
        self.response.out.write(template.render(path, template_values))


class MapData(webapp.RequestHandler):
    """"""

    def get(self):

        res = """{
    "type": "Feature",
    "properties": {
        "name": "Coors Field",
        "amenity": "Baseball Stadium",
        "popupContent": "This is where the Rockies play!"
    },
    "geometry": {
        "type": "Point",
        "coordinates": [51.505, -0.09]
    }
}"""
        # encode and return
        self.response.headers['Content-Type'] = "text/plain"
        self.response.out.write(res)



application = webapp.WSGIApplication([('/map', Map),
                                      ('/mapdata', MapData),
                                      ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

