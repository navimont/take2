"""Take2 API for geocoding an address"""

import settings
import logging
import json
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db
from google.appengine.api.urlfetch import fetch
from take2dbm import Address

class Geocode(webapp.RequestHandler):
    """Return coordinates and neighborhood for a given address"""

    def get(self):
        key = self.request.get("key", None)

        if not key:
            logging.error("no key")
            res = "NO_KEY"
        else:
            address = Address.get(key)

            if not address:
                logging.error("invalid key: %s" % (key))
                res = "INVALID_KEY"
            else:
                # replace all line brakes and spaces in address with +
                adr = []
                if address.adr:
                    adr.extend(address.adr)
                if address.country:
                    adr.append(address.country)
                adr = "+".join(adr)
                adr = adr.replace(" ","+")
                # use geocoding api
                uri = "%s?address=%s&sensor=false" % (settings.GOOGLE_GEOCODING_URI,adr)
                logging.debug("Fetching URI: %s" % (uri))
                try:
                    georaw = fetch(uri, method="GET")
                except DownloadError:
                    logging.error("Connection error (timeout)")
                    res = "CONNECTION_ERROR"
                else:
                    if georaw.status_code != 200:
                        logging.error("Request failed. Status: %s" % georaw.status_code)
                        res = "REQUEST_ERROR"
                    else:
                        try:
                            geo = json.loads(georaw.content)
                        except TypeError as err:
                            logging.error("JSON decoder error: %s" % err)
                            res = "DECODING_TYPE_ERROR"
                        except ValueError as err:
                            logging.error("JSON decoder error: %s" % err)
                            res = "DECODING_VALUE_ERROR"
                        else:
                            if geo['status'] == "OK":
                                # return only lat, lon and neighborhood
                                results = geo['results']
                                if len(results) > 1:
                                    logging.warning ("Geoencoding delivered %d results. Taking the first." % len(results))
                                res = results[0]['geometry']['location']
                                for adr in results[0]['address_components']:
                                    if "neighborhood" in adr['types']:
                                        res['neighborhood'] = adr['short_name']
                                logging.debug("Found: %s" % (res))
                            else:
                                logging.error("bad return status: %s" % (geo['status']))
                                res = geo['status']

        self.response.headers['Content-Type'] = 'text/plain'
        self.response.out.write(res)



application = webapp.WSGIApplication([('/geo.*', Geocode)
                                     ],settings.DEBUG)

def main():
    logging.getLogger().setLevel(settings.LOG_LEVEL)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
