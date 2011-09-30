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
            except TypeError as err:
                logging.error("JSON decoder error: %s" % err)
                res['error'] = "DECODING_TYPE_ERROR"
            except ValueError as err:
                logging.error("JSON decoder error: %s" % err)
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


class Geocode(webapp.RequestHandler):
    """Return coordinates and neighborhood for a given address"""

    def get(self):
        adr = self.request.get("adr", None)

        if not adr:
            logging.error("no address parameter")
            res = "NO_KEY"
        else:
            res = json.dumps(geocode_lookup(adr))

        self.response.headers['Content-Type'] = 'text/plain'
        self.response.out.write(res)



application = webapp.WSGIApplication([('/geo.*', Geocode)
                                     ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

