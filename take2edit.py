"""Take2 search and edit REST Api"""

import settings
import logging
import os
import calendar
from datetime import datetime, timedelta
import yaml
import json
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.db import Key
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from take2dbm import Contact, Person, Company, Take2, FuzzyDate
from take2dbm import Link, Email, Address, Mobile, Web, Other
from take2export import encodeContact


def encodeContactForWebpage(dump, contact, me):
    """Revises some field in the db dump (a strcuture of lists and dictionaries)
    so that the data can be used for the template renderer
    """
    if contact.class_name() == "Person":
        # birthdays are displayed without the year of birth
        if 'birthday' in dump:
            dump['birthday'] = "%d %s" % (contact.birthday.day,
                                         calendar.month_name[contact.birthday.month])
    # find the contact's relation to me (the person who is looged in)
    dump['relation_to_me'] = None
    if me:
        if me.key() == contact.key():
            dump['relation_to_me'] = "%s, that's you!" % (contact.name)
        else:
            # find my link to the contact
            q_rel = Link.all()
            q_rel.filter("contact =", me)
            q_rel.filter("link_to =", contact)
            rel = q_rel.fetch(1)
            if len(rel) > 0:
                assert len(rel) == 1, "too many links from: %s to: %s" % (str(me.key(),str(contact.key())))
                rel = rel[0]
                if contact.class_name() == "Person":
                    dump['relation_to_me'] = "%s is your %s." % (contact.name,rel.link.lower())
                else:
                    dump['relation_to_me'] = "Your relation: %s" % (rel.link.lower())

    return dump


def saveTake2WithHistory(new,old):
    """Saves a new Take2 entity in the datastore. The new object
    replaces the old entity and we keep a history by leaving
    the old entity in the datastore but now pointing to the new one."""

    if new:
        new.put()
        if old:
            old.contact = new
            old.put()


def getCurrentUserPerson(user):
    """Find the person which represents the currently logged in user"""
    q_me = Person.all()
    q_me.filter('user =', user)
    me = q_me.fetch(3)
    if len(me) > 0:
        if len(me) > 1:
            logging.Error ("more than one person with google account: %s [%s]" % (user.nickname,user.user_id))
        me = me[0]
    else:
        me = None

    return me


def getCurrentUserTemplateValues(user, page_uri, template_values=None):
    """Set up a set of template values
    Helpful for rendering the web page with some basic information about the user.
    """
    if not template_values:
        template_values = {}

    if user:
        template_values['loginout_url'] = users.create_logout_url(page_uri)
        template_values['loginout_text'] = 'logout %s' % (user.nickname())
    else:
        template_values['loginout_url'] = users.create_login_url(page_uri)
        template_values['loginout_text'] = 'login'
    return template_values


def MembershipRequired(target):
    """Decorator: Is the currently logged in user (google account) also in the take2 DB?

    Also prepares the google user object, the user's take2 identity and some
    template_values and calls the target function with those as parameters.
    """
    def redirectToSignupPage(self):
        template_values = {'sorry': "Your username is not in the database. Please sign up first."}
        path = os.path.join(os.path.dirname(__file__), 'take2sorry.html')
        self.response.out.write(template.render(path, template_values))
        return

    def wrapper (self):
        # Add extra parameters
        kwargs = {'user': user,
                  'me': me,
                  'template_values': getCurrentUserTemplateValues(user, self.request.uri)}
        return target(self, **kwargs)

    # find my own Person object
    user = users.get_current_user()
    me = getCurrentUserPerson(user)
    if not me:
        return redirectToSignupPage
    else:
        logging.debug("returning wrapper")
        return wrapper

class Take2Search(webapp.RequestHandler):
    """Run a search query over the current user's realm"""

    def get(self):
        user = users.get_current_user()
        me = getCurrentUserPerson(user)
        template_values = getCurrentUserTemplateValues(user,self.request.uri)

        query = self.request.get('query',"")
        contact_key = self.request.get('key',"")
        if self.request.get('attic',"") == 'True':
            archive = True
        else:
            archive = False

        logging.debug("Search query: %s archive: %d key: %s " % (query,archive,contact_key))

        result = []

        #
        # key is given
        #

        if contact_key:
            contact = Contact.get(contact_key)
            # this is basically a db dump
            con = encodeContact(contact, attic=False)
            # adjust fields and add extra fields for website renderer
            con = encodeContactForWebpage(con, contact, me)
            result.append(con)


        #
        # query search
        #

        if query:
            q_res = []
            query1 = query+u"\ufffd"
            logging.debug("Search for %s >= name < %s" % (query,query1))
            q_con = Contact.all()
            q_con.filter("name >=", query).filter("name <", query1)
            q_res.extend(q_con)
            template_values['query'] = query

            for contact in q_res:
                con = encodeContact(contact, attic=False)
                # adjust fields and add extra fields for website renderer
                con = encodeContactForWebpage(con, contact, me)
                result.append(con)

        #
        # birthday search
        #
        daterange_from = datetime.today() - timedelta(days=5)
        daterange_to = datetime.today() + timedelta(days=14)
        # Convert to fuzzydate. Year is not important
        fuzzydate_from = FuzzyDate(day=daterange_from.day,
                                  month=daterange_from.month)
        fuzzydate_to = FuzzyDate(day=daterange_to.day,
                                  month=daterange_to.month)
        logging.debug("Birthday search from: %s to: %s" % (fuzzydate_from,fuzzydate_to))
        q_bd = Person.all()
        q_bd.filter("attic =", False)
        q_bd.filter("birthday >", fuzzydate_from)
        q_bd.filter("birthday <", fuzzydate_to)
        # TODO take care of December/January turnover
        template_values['birthdays'] = []
        # TODO: Fix later!
        if 0:
            for person in q_bd:
                # change birthday encoding from yyyy-mm-dd to dd Month
                person['birthday'] = "%d %s" % (person.birthday.day,
                                                person.month_name[person.birthday.month])
                template_values['birthdays'].append(person)

        # render administration page
        template_values['result'] = result
        path = os.path.join(os.path.dirname(__file__), 'take2search.html')
        self.response.out.write(template.render(path, template_values))


def prepareListOfRelations(relations,selected=None):
    """prepares a list of relations in a
    datastructure ready for the template use"""
    linklist = []
    for rel in relations:
        link = {'link': rel}
        if selected and selected == rel:
            link['selected'] = "selected"
        linklist.append(link)
    return linklist


class PersonEdit(webapp.RequestHandler):
    """Edit existing person or add a new one"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        action,person_key = self.request.get("action", "").split("_")
        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            person = Person.get(person_key)

        template_values['link'] = None

        # define the html form fields for this object
        form = []
        if action == 'edit':
            if me.key() == person.key():
                template_values['myself'] = True
            titlestr = "Edit Person data"
            template_values['name'] = "%s %s" % (person.name,person.lastname)
            template_values['firstname'] = person.name
            if person.lastname:
                template_values['lastname'] = person.lastname
            template_values['birthday'] = person.birthday
            # find relation to this person
            q_link = Link.all()
            q_link.filter("contact =", me)
            q_link.filter("link_to =", person)
            link = q_link.fetch(1)
            if len(link):
                link = link[0]
                template_values['link'] = link.link
                template_values['nickname'] = link.nickname
        else:
            titlestr = "New Person data"

        # prepare drop down menu with preselected relation
        form_file = 'take2form_person.html'
        relations = settings.PERSON_RELATIONS

        template_values['linklist'] = prepareListOfRelations(relations,template_values['link'])
        template_values['form_file'] = form_file
        template_values['titlestr'] = titlestr
        template_values['instance'] = 'person'
        template_values['action'] = action
        template_values['key'] = person_key

        path = os.path.join(os.path.dirname(__file__), form_file)
        self.response.out.write(template.render(path, template_values))


class CompanyEdit(webapp.RequestHandler):
    """Edit existing company or add a new one"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        action,company_key = self.request.get("action", "").split("_")
        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            company = Company.get(company_key)
            template_values['company_name'] = company.name

        # define the html form fields for this object
        form = []
        link = None
        if action == 'edit':
            titlestr = "Edit Institution data"
            template_values['name'] = company.name
            # find relation to this company
            q_link = Link.all()
            q_link.filter("contact =", me)
            q_link.filter("link_to =", company)
            link = q_link.fetch(1)
            if len(link):
                link = link[0]
                template_values['link'] = link.link
        else:
            titlestr = "New Institution data"

        form_file = 'take2form_company.html'
        template_values['linklist'] = prepareListOfRelations(settings.INSTITUTION_RELATIONS,link)
        template_values['form_file'] = form_file
        template_values['titlestr'] = titlestr
        template_values['instance'] = 'company'
        template_values['action'] = action
        template_values['key'] = company_key

        path = os.path.join(os.path.dirname(__file__), form_file)
        self.response.out.write(template.render(path, template_values))


class PersonSave(webapp.RequestHandler):
    """Update/Save contact"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        contact_key = self.request.get("key", "")
        action = self.request.get("action", "")

        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            contact = Contact.get(contact_key)
            instance = contact.class_name().lower()

        #
        # update database
        #
        try:
            # allow the user to make input like 13/8
            bd = ("0%s/0/0" % self.request.get("birthday", "")).split("/")
            day = int(bd[0])
            month = int(bd[1])
            year = int(bd[2])
            if day < 0 or day > 31 or month < 0 or month > 12 or year < 0 or year > 9999:
                raise db.BadValueError('Illegal date')
            if action == 'new':
                person = Person(name=self.request.get("firstname", ""),
                                lastname=self.request.get("lastname", ""),
                                nickname=self.request.get("nickname", ""))
                person.birthday = FuzzyDate(day=day,month=month,year=year)
                person.put()
                contact = person
            else:
                person = contact
                person.name = self.request.get("firstname", "")
                person.lastname = lastname=self.request.get("lastname", "")
                person.birthday = FuzzyDate(day=day,month=month,year=year)
                person.put()
            if not self.request.get("linkselect", None):
                raise db.BadValueError('No relation selected')
        except db.BadValueError as error:
            template_values['errors'] = [error]
        except ValueError as error:
            template_values['errors'] = [error]
        if 'errors' in template_values:
            template_values['linklist'] = prepareListOfRelations(settings.PERSON_RELATIONS,link)
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), self.request.get("form_file"))
            self.response.out.write(template.render(path, template_values))
            return

        # update relation
        me = Person.all().filter("user =", user).fetch(1)[0]
        link = Link.all().filter("contact =", me).filter("link_to =", contact).fetch(1)
        if len(link) > 0:
            link0 = link[0]
        else:
            link0 = None
        link_link = self.request.get("linkselect")
        link_nickname = self.request.get("nickname", "")
        link1 = None
        if not link0 or (link0.link != link_link or link0.nickname != link_nickname):
            # Relation is new or was changed. Create new link
            link1 = Link(parent=link0, contact=me,
                         nickname=link_nickname,
                         link=link_link,
                         link_to=contact)

        db.run_in_transaction(saveTake2WithHistory, new=link1, old=link0)

        self.redirect('/search?key=%s' % str(contact.key()))


class CompanySave(webapp.RequestHandler):
    """Update/Save contact"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        company_key = self.request.get("key", "")
        action = self.request.get("action", "")

        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            company = Company.get(company_key)

        #
        # update database
        #
        try:
            if action == 'new':
                company = Company(name=self.request.get("company_name", ""))
                company.put()
            else:
                company = Company.get(company_key)
                company.name = name=self.request.get("company_name", "")
                company.put()
        except db.BadValueError as error:
            template_values['errors'] = [error]
        except ValueError as error:
            template_values['errors'] = [error]
        if 'errors' in template_values:
            template_values['linklist'] = prepareListOfRelations(settings.INSTITUTION_RELATIONS,link)
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), self.request.get("form_file"))
            self.response.out.write(template.render(path, template_values))
            return

        # update relation
        link = Link.all().filter("contact =", me).filter("link_to =", company).fetch(1)
        if len(link) > 0:
            link0 = link[0]
        else:
            link0 = None
        link_link = self.request.get("linkselect")
        # currently not used for links to company
        link_nickname = self.request.get("nickname", "")
        link1 = None
        if not link0 or (link0.link != link_link or link0.nickname != link_nickname):
            # Relation is new or was changed. Create new link
            link1 = Link(parent=link0,
                         contact=me,
                         nickname=link_nickname,
                         link=link_link,
                         link_to=company)

        db.run_in_transaction(saveTake2WithHistory, new=link1, old=link0)

        self.redirect('/search?key=%s' % str(company.key()))


def prepareListOfCountries(selected=None):
    """prepares a list of countries in a
    datastructure ready for the template use"""
    landlist = []
    for lc in settings.COUNTRIES:
        l0 = lc.values()[0]
        choice = {'country': l0}
        if l0 == selected:
            choice['selected'] = "selected"
        landlist.append(choice)
    return landlist

class Take2Edit(webapp.RequestHandler):
    """Edit existing properties or add something new"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        action,instance,key = self.request.get("action", "").split("_")
        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            t2 = Take2.get(key)
            # consistency checks on POSTed data
            assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
            contact = t2.contact
        else:
            # if a new property is added, key contains the contact key
            contact = Contact.get(key)

        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))

        logging.debug("contact: %s action: %s instance: %s key: %s" %
                      (contact.name,action,instance,key))

        # title() capitalizes first letter
        titlestr = action.title()

        # define the html form fields for this take2 object
        form = []
        if instance == 'address':
            titlestr = titlestr+" address"
            form_file = 'take2form_address.html'
            if action == 'edit':
                template_values['landlist'] = prepareListOfCountries(t2.country)
                template_values['adr'] = "\n".join(t2.adr)
                template_values['lat'] = t2.location.lat
                template_values['lon'] = t2.location.lon
                template_values['landline_phone'] = t2.landline_phone
                template_values['country'] = t2.country
            else:
                template_values['landlist'] = prepareListOfCountries()
        if instance == 'mobile':
            titlestr = titlestr+" mobile phone"
            form_file = 'take2form_mobile.html'
            if action == 'edit':
                template_values['mobile'] = t2.mobile
        elif instance == 'web':
            titlestr = titlestr+" website"
            form_file = 'take2form_web.html'
            if action == 'edit':
                template_values['web'] = t2.web
            else:
                template_values['web'] = 'http://'
        elif instance == 'email':
            titlestr = titlestr+" email"
            form_file = 'take2form_email.html'
            if action == 'edit':
                template_values['email'] = t2.email
        elif instance == 'other':
            titlestr = titlestr+" misc. info"
            form_file = 'take2form_other.html'
            # prepare drop down menu with preselected relation
            taglist = []
            for tag in settings.OTHER_TAGS:
                choice = {'choice': tag}
                if action == 'edit' and tag == t2.what:
                    choice['selected'] = "selected"
                taglist.append(choice)
            template_values['taglist'] = taglist
            if action == 'edit':
                template_values['text'] = t2.text
        else:
            assert True, "Unhandled take2 class: %s" % (take2_instance)

        template_values['titlestr'] = titlestr
        template_values['action'] = action
        if contact.class_name() == "Person":
            template_values['name'] = contact.name+" "+contact.lastname
        else:
            template_values['name'] = contact.name
        template_values['form'] = form
        template_values['instance'] = instance
        template_values['key'] = key
        template_values['form_file'] = form_file

        path = os.path.join(os.path.dirname(__file__), form_file)
        self.response.out.write(template.render(path, template_values))


class Take2Save(webapp.RequestHandler):
    """Save users/properties"""

    @MembershipRequired
    def post(self, user=None, me=None, template_values={}):
        instance = self.request.get("instance", "")
        key = self.request.get("key", "")
        action = self.request.get("action", "")

        assert action in ['new','edit'], "Undefined action: %s" % (action)

        if action == 'edit':
            t2 = Take2.get(key)
            # consistency checks on POSTed data
            assert t2.class_name() == instance.title(), "Edit class name %s does not fit with object %s" % (instance,key)
            contact = t2.contact
        else:
            # if a new property is added, key contains the contact key
            contact = Contact.get(key)

        assert contact.class_name() in ['Person','Contact'], "Object %s key: %s is not a Contact" % (contact.class_name(),str(contact.key()))

        logging.debug("contact: %s instance: %s key: %s" %
                    (contact.name,instance,key))

        #
        # update database
        #

        if action == 'edit':
            # load existing property
            obj0 = Take2.get(key)
        else:
            obj0 = None

        # Instantiate a fresh entity class if the action
        # is edit and some property has changed
        # OR if the action is new
        obj1 = None
        try:
            if instance == 'address':
                country = self.request.get("country", None)
                template_values['landlist'] = prepareListOfCountries(country)
                lat = float("0%s" % self.request.get("lat", ""))
                lon = float("0%s" % self.request.get("lon", ""))
                adr = self.request.get("adr", "").split("\n")
                # quite some effort in order to allow an empty phone number!
                phone = self.request.get("landline_phone", "").replace("None","")
                if len(phone):
                    landline_phone = db.PhoneNumber(phone)
                else:
                    landline_phone = None
                if not obj0 or (obj0.location.lat != lat
                   or obj0.location.lon != lon
                   or obj0.adr != adr
                   or obj0.landline_phone != landline_phone
                   or obj0.country != country):
                    obj1 = Address(parent=obj0,
                                  location=db.GeoPt(lon=lon, lat=lat), adr=adr,
                                  landline_phone=landline_phone, country=country,
                                  contact=contact.key())
            elif instance == 'mobile':
                mobile = db.PhoneNumber(self.request.get("mobile", ""))
                if not obj0 or obj0.mobile != mobile:
                    obj1 = Mobile(parent=obj0,mobile=mobile, contact=contact.key())
            elif instance == 'web':
                web = db.Link(self.request.get("web", ""))
                if not obj0 or obj0.web != web:
                    obj1 = Web(parent=obj0, web=web, contact=contact.key())
            elif instance == 'email':
                email = db.Email(self.request.get("email", ""))
                if not obj0 or obj0.email != email:
                    obj1 = Email(parent=obj0, email=email, contact=contact.key())
            elif instance == 'other':
                what = self.request.get("what", "")
                text = self.request.get("text", "")
                if not obj0 or (obj0.what != what or obj0.text != text):
                    obj1 = Other(parent=obj0, what=what,text=text,contact=contact.key())
            else:
                assert True, "Unhandled instance: %s" % (instance)
        except db.BadValueError as error:
            template_values['errors'] = [error]
        except ValueError as error:
            template_values['errors'] = [error]
        if 'errors' in template_values:
            for arg in self.request.arguments():
                template_values[arg] = self.request.get(arg)
            path = os.path.join(os.path.dirname(__file__), self.request.get("form_file"))
            self.response.out.write(template.render(path, template_values))
            return

        # new and old objects will be saved/updated
        db.run_in_transaction(saveTake2WithHistory, new=obj1,old=obj0)

        self.redirect('/search?key=%s' % str(contact.key()))

application = webapp.WSGIApplication([('/search.*', Take2Search),
                                      ('/editcompany', CompanyEdit),
                                      ('/savecompany', CompanySave),
                                      ('/editperson', PersonEdit),
                                      ('/saveperson', PersonSave),
                                      ('/edit.*', Take2Edit),
                                      ('/save.*', Take2Save),
                                     ],debug=True)

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()

