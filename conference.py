#!/usr/bin/env python

from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.ext import ndb
from google.appengine.api import memcache
from google.appengine.api import taskqueue

from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import TeeShirtSize
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import Session
from models import SessionForm
from models import SessionForms
from models import BooleanMessage
from models import ConflictException
from models import StringMessage

from settings import WEB_CLIENT_ID
from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT ANNOUNCEMENTS"
MEMCACHE_FEATURED_SPEAKER = "FEATURED SPEAKER FOR THIS CONFERENCE"

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": ["Default", "Topic"],
}

OPERATORS = {
    'EQ': '=',
    'GT': '>',
    'GTEQ': '>=',
            'LT': '<',
            'LTEQ': '<=',
            'NE': '!='
}

FIELDS = {
    'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
}


CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)


SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_BYTYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2),
)

SESSIONS_BY_SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)

WISH_LIST_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    SessionKey=messages.StringField(1),
)

WISH_LIST_BYTYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    typeOfSession=messages.StringField(1),
)

WISH_LIST_BYSPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)


PROBLEM_QUERY_PARAM_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    typeOfSession=messages.StringField(1),
    startTime=messages.StringField(2),
)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference',
               version='v1',
               allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
               scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(
                        pf, field.name, getattr(
                            TeeShirtSize, getattr(
                                prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if
        non-existent."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        # get the entity from datastore by using get() on the key
        profile = p_key.get()
        if not profile:
            profile = Profile(
                key=p_key,
                displayName=user.nickname(),
                mainEmail=user.email(),
                teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
            )
            # save the profile to datastore
            profile.put()

        return profile      # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
            # TODO 4
            # put the modified profile to datastore
            prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning
        ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound
        # Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on
        # start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(
                data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(
                data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
            setattr(request, "seatsAvailable", data["maxAttendees"])

        # make Profile Key from user ID
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID with Profile key as parent
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                              'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email'
                      )

        return request

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
                      http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    # Get the conferences so that we can register them.
    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' %
                request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        # conferences = Conference.query()
        conferences = self._getQuery(request)

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "")
                   for conf in conferences]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getConferencesCreated',
                      http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # make profile key
        p_key = ndb.Key(Profile, getUserId(user))
        # create ancestor query for this user
        conferences = Conference.query(ancestor=p_key)
        # get the user profile and display name
        prof = p_key.get()
        displayName = getattr(prof, 'displayName')
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[
                self._copyConferenceToForm(
                    conf,
                    displayName) for conf in conferences])

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='filterPlayground',
                      http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        q = Conference.query()
        # Simple filter usage:

        # 1. City equals London

        q = q.filter(Conference.city == "London")

        # 2. Topic equals medical innovation
        q = q.filter(Conference.topics == "Medical Innovations")

        # 3. Order by conference name:
        q = q.order(Conference.name)

        # 4. All Conferences in specific Month (October)

        # q = q.filter(Conference.month == 10)
        q = q.filter(Conference.maxAttendees > 10)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(
                filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name)
                     for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # Check if inequality operation has been used in previous
                # filters.
                # Disallow the filter if inequality was performed on a
                # different field before.
                # Track the field on which the inequality operation is
                # performed.
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    # (xg = True) means cross group or two different entity groups.
    # Each profile can register for conferences created by other profiles
    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        print "This is wsck: %s" % wsck
        print "This is wsck type: %s" % type(wsck)

        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    # Register for conference:
    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    # Unregister from conference
    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        # get user profile
        prof = self._getProfileFromUser()

        # get conferenceKeysToAttend from profile.
        # to make a ndb key from websafe key use:
        # ndb.Key(urlsafe=my_websafe_key_string)
        conf_keys = [ndb.Key(urlsafe=wsck)
                     for wsck in prof.conferenceKeysToAttend]

        # fetch conferences from datastore.
        # Use get_multi(array_of_keys) to fetch all keys at once.
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId)
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, "")
                                      for conf in conferences]
                               )

# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)


# -------------------Sessions objects-------------------------------------

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                # convert Date to date string; just copy others
                if field.name.startswith(
                        'dat') or field.name.startswith('start'):
                    setattr(sf, field.name, str(getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
            elif field.name == "websafeConferenceKey":
                setattr(sf, field.name, session.key.urlsafe())
        sf.check_initialized()
        return sf

    def _createSessionObject(self, request):
        """Create Session object, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Session 'name' field required")

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        # convert dates from strings to Date objects;
        if data['date']:
            data['date'] = datetime.strptime(
                data['date'][:10], "%Y-%m-%d").date()

        # convert time from strings to time objects;
        if data['startTime']:
            data['startTime'] = datetime.strptime(
                data['startTime'], "%H:%M").time()
        mykey = data['websafeConferenceKey']
        conf = ndb.Key(urlsafe=data['websafeConferenceKey']).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' %
                request.websafeConferenceKey)

        # Retrieve Conference ID
        c_key = conf.key

        # Make sure that only creator of conference can add sessions to
        # conference:
        parent_key = conf.key.parent().id()
        profile = self._getProfileFromUser()
        p_key = profile.key.id()

        if parent_key != p_key:
            raise endpoints.UnauthorizedException(
                'Only creator of the conference can add sessions')

        # allocate new Session ID with Conference key as parent
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        # make Session key from ID
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key
        del data['websafeConferenceKey']

        # Collect names of all speakers presenting at the conference
        # along with the session names that they are speaking at.
        sessions = Session.query(ancestor=c_key)

        # Fetch all speakers speaking at a conference
        speakers = sessions.fetch(projection=Session.speaker)

        session_names = sessions.filter(Session.speaker == request.speaker)

        # Commit session to NDB
        Session(**data).put()

        # Variable to count number of times the speaker is speaking at
        # the conference before creating new session
        counter = 0
        for speaker in speakers:
            if speaker.speaker == request.speaker:
                counter = counter + 1
        # if speaker already speaks at this conference make him/her a
        # featured speaker by creating a task.
        if counter > 0:
            taskqueue.add(params={'speaker': request.speaker,
                                  'conference_key': mykey},
                          url='/tasks/featured_speaker')
        return request

    @endpoints.method(SessionForm, SessionForm, path='session',
                      http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)

    # Given a conference, returns all sessions
    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
                      path='getSessions',
                      http_method='POST',
                      name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Query for all sessions for a given conference."""
        wsck = request.websafeConferenceKey
        conf_key = ndb.Key(urlsafe=wsck)
        sessions = Session.query(ancestor=conf_key).fetch()
        for session in sessions:
            print "Sesson Name is: %s" % session.name
        # return individual SessionForm object per Conference
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions])

    # Query for Sessions by type.
    @endpoints.method(SESSION_BYTYPE_GET_REQUEST, SessionForms,
                      path='getSessionsbyType',
                      http_method='POST',
                      name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Query for Sessions by type."""
        wsck = request.websafeConferenceKey
        session_type = request.typeOfSession
        conf_key = ndb.Key(urlsafe=wsck)
        sessions = Session.query(ancestor=conf_key)
        sessions = sessions.filter(
            Session.typeOfSession == session_type).fetch()
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions])

    # Query for particular speaker across all conferences
    @endpoints.method(SESSIONS_BY_SPEAKER_GET_REQUEST, SessionForms,
                      path='getSpeakerSessions',
                      http_method='POST',
                      name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Query for Sessions by type."""
        speaker = request.speaker
        sessions = Session.query()
        sessions = sessions.filter(Session.speaker == speaker)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions])

    # Add session to Wishlist
    @endpoints.method(WISH_LIST_GET_REQUEST, StringMessage,
                      path='addToWishList',
                      http_method='POST',
                      name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add Session to Wish List"""
        prof = self._getProfileFromUser()  # get user Profile

        # check if session exists given sessionKey
        # get session, check that it exists
        session_key = request.SessionKey
        session = ndb.Key(urlsafe=session_key).get()
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % session_key)

        # Add a session key to profile
        prof.wishlistSessionKeys.append(session_key)

        # write things back to the datastore & return
        prof.put()
        return StringMessage(data=session_key)

    # Retrieve Wishlist
    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='sessionwishlist',
                      http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Get list of sessions from user wishlist."""
        # Get user profile
        prof = self._getProfileFromUser()

        # Get wishlistSessionKeys from profile.
        session_keys = [ndb.Key(urlsafe=session_key)
                        for session_key in prof.wishlistSessionKeys]

        # Fetch session from datastore.
        # Use get_multi(array_of_keys) to fetch all keys at once.
        sessions = ndb.get_multi(session_keys)

        # return set of SessionForm objects per Session
        return SessionForms(items=[self._copySessionToForm(session)
                                   for session in sessions]
                            )

    # Retrieve Wishlist by type
    @endpoints.method(WISH_LIST_BYTYPE_GET_REQUEST, SessionForms,
                      path='sessionwishlistbytype',
                      http_method='GET', name='getWishlistbyType')
    def wishlist_by_Type(self, request):
        """Get list of sessions from user wishlist by type."""
        # Get user profile
        prof = self._getProfileFromUser()
        session_type = request.typeOfSession
        # Get wishlistSessionKeys from profile.
        session_keys = [ndb.Key(urlsafe=session_key)
                        for session_key in prof.wishlistSessionKeys]
        sessions = ndb.get_multi(session_keys)
        wishlist = []
        for session in sessions:
            if session.typeOfSession == session_type:
                wishlist.append(session)
        return SessionForms(items=[self._copySessionToForm(wish)
                                   for wish in wishlist]
                            )

    # Retrieve Wishlist by Speaker
    @endpoints.method(WISH_LIST_BYSPEAKER_GET_REQUEST, SessionForms,
                      path='sessionwishlistbyspeaker',
                      http_method='GET', name='getWishlistbySpeaker')
    def wishlist_by_Speaker(self, request):
        """Get list of sessions from user wishlist by speaker."""
        # Get user profile
        prof = self._getProfileFromUser()
        session_speaker = request.speaker
        # Get wishlistSessionKeys from profile.
        session_keys = [ndb.Key(urlsafe=session_key)
                        for session_key in prof.wishlistSessionKeys]
        sessions = ndb.get_multi(session_keys)
        wishlist = []
        for session in sessions:
            if session.speaker == session_speaker:
                wishlist.append(session)
        return SessionForms(items=[self._copySessionToForm(wish)
                                   for wish in wishlist]
                            )

    # Solution to query related problem
    @endpoints.method(PROBLEM_QUERY_PARAM_GET_REQUEST, SessionForms,
                      path='problemquery',
                      http_method='GET', name='problemQuery')
    def twoIneqFiltersOnDifProp(self, request):
        """Two inequality filters on different properties."""
        session_type = request.typeOfSession
        start_time = request.startTime
        start_time = datetime.strptime(start_time, "%H:%M").time()
        q = Session.query()
        q = q.filter(Session.typeOfSession != session_type)
        print q
        p = Session.query()
        p = p.filter(Session.startTime < start_time)
        my_results = []
        for session in p:
            for sess in q:
                if (session == sess and session.startTime is not None and
                        sess.typeOfSession is not None):
                            my_results.append(session)
        return SessionForms(items=[self._copySessionToForm(each_result)
                                   for each_result in my_results])

    # Get Featured Speaker
    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='session/featured/get',
                      http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return Featured speaker from memcache."""
        featured = memcache.get(MEMCACHE_FEATURED_SPEAKER)
        if not featured:
            featured = ""
        return StringMessage(data=featured)

# registers API
api = endpoints.api_server([ConferenceApi])
