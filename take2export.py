"""Take2 import/export REST Api"""

import logging
import os
import json
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from epoidbm import Epoicon, Osmtag


class LoginPage(webapp.RequestHandler):
    def get(self):
        self.redirect(users.create_login_url('index.html'))

class LogoutPage(webapp.RequestHandler):
    def get(self):
        self.redirect(users.create_logout_url('index.html'))

class EpoiAdminPage(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()

        # not logged in
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return

        template_values = {'nickname': user.nickname()}

        # not an administrator
        if not users.is_current_user_admin():
            path = os.path.join(os.path.dirname(__file__), 'sorrynoadmin.html')
            self.response.out.write(template.render(path, template_values))
            return

        # find all icons in icondir directory
        # note that icondir is only used to import new icon files
        # into the storage. The files will later be served from
        # the storage, not from icondir!
        iconfiles = os.listdir(icondir)
        # keep only those with ending *.png
        iconfiles = [ic for ic in iconfiles if ic.endswith('.png') ]
        logging.debug ("%3d     iconfiles found: %s" % (len(iconfiles),[", ".join(iconfiles)]))

        # find all existing epoi icons in the storage
        dbicons = Epoicon.all()
        dbiconfiles = [dbi.file for dbi in dbicons]
        logging.debug ("%3d icons in storage" % (len(dbiconfiles)))

        #
        # Those icons which are in the file list but not in the storage
        # have to be added to the storage
        #
        new_icons = set(iconfiles).difference(set(dbiconfiles))
        logging.debug ("%3d new iconfiles found: %s" % (len(new_icons),[", ".join(new_icons)]))
        imported_icons = []
        for ni in new_icons:
            try:
                fp = open(os.path.join(icondir,ni), 'rb')
                try:
                    icondata = fp.read()
                finally:
                    fp.close()
                imported_icons.append(ni)
            except IOError:
                logging.critical("Could not read file %s/%s" % (icondir,ni))
            # The name has to be adjusted by the user. For now use
            # the upper case filename without ending
            dbi = Epoicon(name=ni[:-4].upper(), file=ni, icon=icondata)
            dbi.put()
        logging.debug ("%3d iconfiles imported:  %s" % (len(imported_icons),[",".join(imported_icons)]))

        icons = []
        for epi in Epoicon.all():
            icons.append({'file': os.path.join('icon',epi.file),
                          'id':str(epi.key()),
                          'name':epi.name})

        template_values['icons'] = icons

        # render administration page
        path = os.path.join(os.path.dirname(__file__), 'epoiadmin.html')
        self.response.out.write(template.render(path, template_values))

class Take2Export(webapp.RequestHandler):
    """Export the relation between icons and osm tags (backup)"""

    def encodeTake2(obj_class, contact, archived = False)
        """Encodes objects derived from Take2 class
        into a python data structure.
        q_object is a query"""

        q_obj = obj_class.all()
        q_obj.filter("contact =", contact.key())

        for obj in q_object:
            if

    def encodeContact(self, contact, archived=False)
        """Encodes Contact data for export and returns a
        python data structure of dictionaries and lists.
        If archived=True, data will include the
        complete history and also archived data.
        """
        res = {}
        res['key'] = str(contact.key())
        res['name'] = contact.name
        if contact.class_name == "Person":
            res['type'] = "person"
            # google account
            res['user'] = user.nickname()
            # personal nickname
            res['nickname'] = contact.nickname
            res['lastname'] = contact.lastname
            res['birthday'] = contact.birthday
        elif contact.class_name == "Company":
            res['type'] = "company"


        encodeTake2(, archive)


        res['links'] = []
        for link in contact.link_set:
            ln = {}
            ln['timestamp'] = link.timestamp
            ln['take2'] = link.take2
            ln['link'] = link.link
            ln['link_to'] = link_to.link_to
            res['links'].append(ln)

        res['addresses'] = []
        for address in contact.address_set:
            addr = {}
            addr['location'] = address.location
            addr['adr'] = address.adr
            addr['landline_phone'] = address.landline_phone
            addr['country'] = address.country
            addr['timestamp'] = addr.timestamp
            addr['take2'] = addr.take2
            res['addresses'].append(addr)

        res['mobiles'] = []
        for mobile in contact.mobile_set:
            mobi = {}
            mobi['timestamp'] = mobile.timestamp
            mobi['take2'] = mobile.take2
            mobi['mobile'] = mobile.mobile
            res['mobiles'].append(mobi)

        res['webs'] = []
        for web in contact.web_set:
            wb = {}
            wb['timestamp'] = web.timestamp
            wb['take2'] = web.take2
            wb['web'] = web.web
            res['webs'].append(wb)

        res['emails'] = []
        for email in contact.email_set:
            em = {}
            em['timestamp'] = email.timestamp
            em['take2'] = email.take2
            em['email'] = email.email
            res['emails'].append(em)

        res['notes'] = []
        for note in contact.note_set:
            nt = {}
            nt['timestamp'] = note.timestamp
            nt['take2'] = note.take2
            nt['web'] = note.note
            res['notes'].append(nt)

        res['others'] = []
        for other in contact.other_set:
            ot = {}
            ot['timestamp'] = other.timestamp
            ot['take2'] = other.take2
            ot['web'] = other.note
            res['others'].append(ot)

        return res



    def get(self):
        user = users.get_current_user()

        # not logged in
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return

        template_values = {'nickname': user.nickname()}

        if self.request.get('archive',"") == 'True':
            archive = True
        else:
            archive = False

        self.response.headers['Content-Type'] = 'application/json'

        # Administrator exports everything
        if users.is_current_user_admin():
            q_con = Contact.all()

        else:
            q_us = Contact.all()
            q_us.filter("user =", user)
            us = q_us.fetch(1)
            if len(us) != 1:
                logging.Critical("Found wrong # of user: %s [%s]" % (user.nickname(),
                    ", ".join[u.name for u in us])
                self.error(500)
                return
            else:
            logging.info("export user: %s name: " % (user.nickname(), us[0].)
            self.response.out.write(encodeContact(self, us, archived=archive))


class Take2Import(webapp.RequestHandler):
    """Import data into database"""
    def get(self):
        user = users.get_current_user()

        # not logged in
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return

        template_values = {'nickname': user.nickname()}

        # not an administrator
        if not users.is_current_user_admin():
            path = os.path.join(os.path.dirname(__file__), 'sorrynoadmin.html')
            self.response.out.write(template.render(path, template_values))
            return

        # filename is given in URL
        file = self.request.get('file')
        if not file:
            logging.Error ("No 'file' in URL parameters")
            self.error(500)
            return

        try:
            fp = open(file,'r')
        except IOError:
            logging.Error ("Can't open backup file: %s" % (file))
            self.error(500)
            return

        icons = json.load(fp)
        for icon in icons:
            # open icon file
            try:
                iconfp = open(os.path.join(icondir,icon['file']),'r')
            except IOError:
                logging.Error ("Can't open icon file: %s/%s" % (icondir,file))
                continue

            # instantiate icon object
            epoicon = Epoicon(key=icon['key'], name=icon['name'], file=icon['file'], icon=iconfp.read())
            iconfp.close()
            epoicon.put()

        fp.close()
        self.redirect('/epoiadmin')


application = webapp.WSGIApplication([('/epoiadmin/icon.*', EpoiAdminEditIconPage),
                                      ('/epoiadmin', EpoiAdminPage),
                                      ('/take2/import.*', EpoiAdminImportIcons),
                                      ('/take2/export', EpoiAdminExportIcons),
                                      ('/login', LoginPage),
                                      ('/logout', LogoutPage)],debug=True)

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

