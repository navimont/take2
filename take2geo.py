"""Take2 API location services"""

import settings
import logging
from datetime import datetime, timedelta
from django.utils import simplejson as json
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db
from google.appengine.api.urlfetch import fetch
from take2dbm import Address
from take2access import get_login_user


class LocationHandler(webapp.RequestHandler):
    """A user sends her location"""

    def get(self):
        login_user = get_login_user()
        # must be logged in to submit position
        if not login_user:
            self.error(500)
            return

        lat = self.request.get("lat", None)
        lon = self.request.get("lon", None)
        place = self.request.get("place", None)
        user = self.request.get("user", None)
        # PERMISSION_DENIED (1)
        # POSITION_UNAVAILABLE (2)
        # TIMEOUT (3)
        # UNKNOWN_ERROR (0)
        # firefox supports only (1) in case of a permanent denial
        err = self.request.get("err", None)
        logging.debug("LocationHandler.get() err: %s lat: %s lon: %s place: %s" % (err,lat,lon,place))

        if not err:
            login_user.location.lat = float(lat)
            login_user.location.lon = float(lon)
            login_user.place = place
            login_user.location_timestamp = datetime.now()
            # ask again in an hour
            login_user.ask_geolocation = datetime.now() + timedelta(hours=1)
            login_user.put()

        # response is always OK
        self.response.set_status(200)
        return


application = webapp.WSGIApplication([('/location.*', LocationHandler)
                                     ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

