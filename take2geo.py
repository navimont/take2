"""Take2 API for geocoding an address"""

import settings
import logging
from django.utils import simplejson as json
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db
from google.appengine.api.urlfetch import fetch
from take2dbm import Address
from take2access import get_login_user

def geocode_lookup(adr):
    """performs a geo lookup for the given address

    adr is an address string including the country
    returns a datastructure containing lat, lon and
    a adr_zoom element which features a list of administrative
    entities for the address, such as:
    USA, NY, New York, Brooklyn, Fort Greene
    """

    # replace all line brakes and spaces in address with +
    adr = adr.replace(" ","+")
    # use geocoding api
    uri = "%s?address=%s&sensor=false" % (settings.GOOGLE_GEOCODING_URI,adr)
    logging.debug("Fetching URI: %s" % (uri))

    res = {}
    try:
        georaw = fetch(uri, method="GET")
    except DownloadError:
        logging.error("Connection error (timeout)")
        res['error'] = "CONNECTION_ERROR"
    else:
        if georaw.status_code != 200:
            logging.error("Request failed. Status: %s" % georaw.status_code)
            res['error'] = "REQUEST_ERROR"
        else:
            try:
                geo = json.loads(georaw.content)
            except TypeError:
                logging.error("JSON decoder error: TypeError")
                res['error'] = "DECODING_TYPE_ERROR"
            except ValueError:
                logging.error("JSON decoder error: ValueError")
                res['error'] = "DECODING_VALUE_ERROR"
            else:
                if geo['status'] == "OK":
                    # return only lat, lon and neighborhood
                    results = geo['results']
                    if len(results) > 1:
                        logging.warning ("Geoencoding delivered %d results. Taking the first." % len(results))
                    res = results[0]['geometry']['location']
                    res['lon'] = res['lng']
                    del res['lng']
                    adr_zoom = []
                    # zoom into address: earth, country, state, province etc.
                    for zoom in ['country','administrative_area_level_1','administrative_area_level_2','administrative_area_level_3','locality','neighborhood']:
                        for level in results[0]['address_components']:
                            if zoom in level['types']:
                                adr_zoom.append(level['long_name'])
                    res['adr_zoom'] = adr_zoom
                    logging.debug("Found: %s" % (res))
                else:
                    logging.error("bad return status: %s" % (geo['status']))
                    res['error'] = geo['status']
    return res


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
        user = self.request.get("user", None)
        # PERMISSION_DENIED (1)
        # POSITION_UNAVAILABLE (2)
        # TIMEOUT (3)
        # UNKNOWN_ERROR (0)
        err = self.request.get("err", None)

        logging.debug("%s %s %s %s" % (lat,lon,user,err))

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

