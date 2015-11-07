Conference application

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][1].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting
   your local server's address (by default [localhost:8080][2].)
1. Generate your client library(ies) with [the endpoints tool][3].
1. Deploy your application.


## Task 1: Design Choices for Session Class
Conference sessions are modeled by Session class. 

Sessions are modeled as events that do not span multiple days in contrast to 
Conferences that can last longer than a day. 

"date" property of a Session class specifies a date when a session takes place. The type of this member is DateProperty and not DateTime property as sessions start time is modeled by a different property--startTime. 

"startTime" specifies start time of a session. Only subclass of DateTime property type, i.e., TimeProperty is chosen for this member as session's date is modeled by a different member. 


All other properties of a Session class are of type StringProperty including Session speaker. 
Session speaker is modeled by "speaker" member of the class Session. 

"speaker" is of StringProperty type--a flexible choice since this type is a unicode string up to 1500 bytes. 

## Task 2: Session Wishlist
See Add session to Wishlist -- line 701 in conference.py file. 
Please note that session is added to wishlist by supplying a Session entity Key, not ID. 

## Task 3: Additional Queries
1. Retrieve wishlist by type: getWishlistbyType -- line 752 in conference.py file.
Users are able to retrive sessions that they added to wishlist by type of session, such as Lecture, workshop etc. 

2. Retrieve wishlist by speaker: getWishlistbySpeaker -- line 773 in conference.py file. 
Users are able to quickly find the sessions that features their favorite speaker that they added to wishlist. 

## Task 3: Query Problem
Multiple inequality filters can only be applied to the same property in NDB database. 
When a single query contains inequality filters on more than one property datastore rejects it. 

In a presented original query problem inequalities(!= and >) are applied to two properties of the Session class: "typeofSession" and startTime. 

One proposed solution is to break down an original query into two separate queries where each query applies inequality only to a single property. 
Intersection of resultant sets of these queries will be a solution to an original problem.

We can filter for intersection of sets of results from queries using == operator in Python because all 3 points apply:
1. Session query results are of type Session
2. Session class inherits from ndb.Model class
3. ndb.Model class implements equality comparison method below: 

  def __eq__(self, other):
    """Compare two entities of the same class for equality."""
    if other.__class__ is not self.__class__:
      return NotImplemented
    if self._key != other._key:
      # TODO: If one key is None and the other is an explicit
      # incomplete key of the simplest form, this should be OK.
      return False
    return self._equivalent(other)

See [NDB source code] [4] for full implementation details. 
 
For implementation of proposed solution to original query problem see problemQuery endpoint

conference.py --line 794 -- Solution to query related problem




[1]: https://console.developers.google.com/
[2]: https://localhost:8080/
[3]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
[4]: https://github.com/GoogleCloudPlatform/datastore-ndb-python/blob/3360752d371e84d9d3433be97a75324f267ec8f8/ndb/model.py