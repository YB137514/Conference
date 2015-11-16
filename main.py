#!/usr/bin/env python
import webapp2
from google.appengine.ext import ndb
from models import Session
from google.appengine.api import app_identity
from google.appengine.api import mail
from google.appengine.api import memcache
from conference import ConferenceApi

MEMCACHE_FEATURED_SPEAKER = "FEATURED SPEAKER FOR THIS CONFERENCE"


class SetAnnouncementHandler(webapp2.RequestHandler):

    def get(self):
        """Set Announcement in Memcache."""
        # _cacheAnnouncement() sets announcement in Memcache
        ConferenceApi._cacheAnnouncement()
        self.response.set_status(204)


class SendConfirmationEmailHandler(webapp2.RequestHandler):

    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )


# This task will set featured speaker and assosiated sessions in memcache
class Featured_Speaker(webapp2.RequestHandler):

    def post(self):
        """Make a speaker a feature speaker if he/she presents more than
        once at a conference"""
        safe_key = self.request.get('conference_key')
        conf = ndb.Key(urlsafe=safe_key).get()

        # Retrieve Conference ID
        c_key = conf.key

        # Retrieve featured speaker
        speaker = self.request.get('speaker')

        # Find sessions associated with featured speaker
        sessions = Session.query(ancestor=c_key)
        # Return the number of times that the speaker is speaking
        num_of_times_speaking = sessions.filter(
            Session.speaker == speaker).count()
        if num_of_times_speaking > 1:
            session_names = sessions.filter(Session.speaker == speaker)
            featured_speaker = '%s %s\n %s %s' % (
                'New Featured Speaker is: ', speaker,
                'Presenting on the following topics:\n',
                ', \n'.join(name.name for name in session_names))

            # Set featured speaker in memcache
            memcache.set(MEMCACHE_FEATURED_SPEAKER, featured_speaker)
            self.response.set_status(204)


app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
    ('/tasks/featured_speaker', Featured_Speaker),
], debug=True)
