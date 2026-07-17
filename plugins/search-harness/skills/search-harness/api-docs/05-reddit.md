---
source: reddit.com: api documentation
url: https://www.reddit.com/dev/api
final_url: https://www.reddit.com/dev/api
language: en
fetched_at: 2026-05-04
bytes: 72766
---

# reddit.com: api documentation

> Reddit gives you the best of the internet in one place. Get a constantly updating feed of breaking news, fun stories, pics, memes, and videos just for you. Passionate about something niche? Reddit has thousands of vibrant communities with people that share your interests. Alternatively, find out what’s trending across all of Reddit on r/popular. Reddit is also anonymous so you can be yourself, with your Reddit profile and persona disconnected from your real-world identity.

This is automatically-generated documentation for the reddit API.

Please take care to respect our API access rules.

## overview

### listings

Many endpoints on reddit use the same protocol for controlling pagination and
filtering. These endpoints are called Listings and share five common
parameters:

```
after
```

/

```
before
```

,

```
limit
```

,

```
count
```

, and

```
show
```

.

Listings do not use page numbers because their content changes so frequently.
Instead, they allow you to view slices of the underlying data. Listing JSON
responses contain

```
after
```

and

```
before
```

fields which are equivalent to the
"next" and "prev" buttons on the site and in combination with

```
count
```

can be
used to page through the listing.

The common parameters are as follows:

* ```
  after
  ```

  /

  ```
  before
  ```

  - only one should be specified. these indicate the fullname of an item in the listing to use as the anchor point of the slice.
* ```
  limit
  ```

  - the maximum number of items to return in this slice of the listing.
* ```
  count
  ```

  - the number of items already seen in this listing. on the html site, the builder uses this to determine when to give values for

  ```
  before
  ```

  and

  ```
  after
  ```

  in the response.
* ```
  show
  ```

  - optional parameter; if

  ```
  all
  ```

  is passed, filters such as "hide links that I have voted on" will be disabled.

To page through a listing, start by fetching the first page without specifying
values for

```
after
```

and

```
count
```

. The response will contain an

```
after
```

value
which you can pass in the next request. It is a good idea, but not required, to
send an updated value for

```
count
```

which should be the number of items already
fetched.

### modhashes

A modhash is a token that the reddit API requires to help prevent CSRF. Modhashes can be obtained via the /api/me.json call or in response data of listing endpoints.

The preferred way to send a modhash is to include an

```
X-Modhash
```

custom HTTP
header with your requests.

Modhashes are not required when authenticated with OAuth.

### fullnames

A fullname is a combination of a thing's type (e.g.

```
Link
```

) and its unique ID
which forms a compact encoding of a globally unique ID on reddit.

Fullnames start with the type prefix for the object's type, followed by the
thing's unique ID in base 36. For
example,

```
t3_15bfi0
```

.

t1\_
Comment

t2\_
Account

t3\_
Link

t4\_
Message

t5\_
Subreddit

t6\_
Award

### response body encoding

For legacy reasons, all JSON response bodies currently have

```
<
```

,

```
>
```

, and

```
&
```

replaced with

```
&lt;
```

,

```
&gt;
```

, and

```
&amp;
```

, respectively. If you wish to opt out
of this behaviour, add a

```
raw_json=1
```

parameter to your request.

## account

### GET /api/v1/me/prefsidentity

Return the preference settings of the logged in user

fields


A comma-separated list of items from this set:

### PATCH /api/v1/me/prefsaccount

This endpoint expects JSON data of this format

### GET /prefs/wherereadrss support

* → /prefs/friends
* → /prefs/blocked
* → /prefs/messaging
* → /prefs/trusted
* → /api/v1/me/friends
* → /api/v1/me/blocked

## announcements

### GET /api/announcements/v1announcements

* → /api/announcements/v1/unread

Fetch announcements from Reddit.

after


(beta) fullname of an announcement, prefixed


before


(beta) fullname of an announcement, prefixed


limit


an integer between 1 and 100

### POST /api/announcements/v1/hideannouncements

Accepts a list of announcement fullnames (

```
ann_
```

)
and marks them hidden if they belong to the authenticated user

ids


(beta) comma separated list of announcement fullnames, prefixed

### POST /api/announcements/v1/readannouncements

Accepts a list of announcement fullnames (

```
ann_
```

)
and marks them read if they belong to the authenticated user

ids


(beta) comma separated list of announcement fullnames, prefixed

### POST /api/announcements/v1/read\_allannouncements

Marks all unread announcements as read for the authenticated user

## captcha

## emoji

### POST /api/v1/subreddit/emoji.jsonstructuredstyles

Add an emoji to the DB by posting a message on emoji\_upload\_q. A job processor that listens on a queue, uses the s3\_key provided in the request to locate the image in S3 Temp Bucket and moves it to the PERM bucket. It also adds it to the DB using name as the column and sr\_fullname as the key and sends the status on the websocket URL that is provided as part of this response.

This endpoint should also be used to update custom subreddit emojis with new images. If only the permissions on an emoji require updating the POST\_emoji\_permissions endpoint should be requested, instead.

mod\_flair\_only


boolean value


name


Name of the emoji to be created. It can be alphanumeric without any special characters except '-' & '\_' and cannot exceed 24 characters.


post\_flair\_allowed


boolean value


s3\_key


S3 key of the uploaded image which can be obtained from the S3 url. This is of the form subreddit/hash\_value.


user\_flair\_allowed


boolean value

### DELETE /api/v1/subreddit/emoji/emoji\_namestructuredstyles

Delete a Subreddit emoji. Remove the emoji from Cassandra and purge the assets from S3 and the image resizing provider.

### POST /api/v1/subreddit/emoji\_asset\_upload\_s3.jsonstructuredstyles

Acquire and return an upload lease to s3 temp bucket. The return value of this function is a json object containing credentials for uploading assets to S3 bucket, S3 url for upload request and the key to use for uploading. Using this lease the client will upload the emoji image to S3 temp bucket (included as part of the S3 URL).

This lease is used by S3 to verify that the upload is authorized.

filepath


name and extension of the image file e.g. image1.png


mimetype


mime type of the image e.g. image/png

### POST /api/v1/subreddit/emoji\_custom\_sizestructuredstyles

Set custom emoji size.

Omitting width or height will disable custom emoji sizing.

height


an integer between 1 and 40 (default: 0)


width


an integer between 1 and 40 (default: 0)

### GET /api/v1/subreddit/emojis/allread

Get all emojis for a SR. The response includes snoomojis as well as emojis for the SR specified in the request.

The response has 2 keys: - snoomojis - SR emojis

## flair

### POST [/r/subreddit]/api/clearflairtemplatesmodflair

api\_type


the string


flair\_type


one of (


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/deleteflairmodflair

api\_type


the string


name


a user by name


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/deleteflairtemplatemodflair

api\_type


the string


flair\_template\_id

uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/flairmodflair

### PATCH [/r/subreddit]/api/flair\_template\_ordermodflair

Update the order of flair templates in the specified subreddit.

Order should contain every single flair id for that flair type; omitting any id will result in a loss of data.

flair\_type


one of (


subreddit


subreddit name


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/flairconfigmodflair

api\_type


the string


flair\_enabled


boolean value


flair\_position


one of (


flair\_self\_assign\_enabled


boolean value


link\_flair\_position


one of (`


link\_flair\_self\_assign\_enabled


boolean value


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/flaircsvmodflair

Change the flair of multiple users in the same subreddit with a single API call.

Requires a string 'flair\_csv' which has up to 100 lines of the form
'

```
user
```

,

```
flairtext
```

,

```
cssclass
```

' (Lines beyond the 100th are ignored).

If both

```
cssclass
```

and

```
flairtext
```

are the empty string for a given

```
user
```

, instead clears that user's flair.

Returns an array of objects indicating if each flair setting was applied, or a reason for the failure.

flair\_csv


comma-seperated flair information


uh / X-Modhash header


a modhash

### GET [/r/subreddit]/api/flairlistmodflair

### POST [/r/subreddit]/api/flairselectorflair

Return information about a users's flair options.

If

```
link
```

is given, return link flair options for an existing link.
If

```
is_newlink
```

is True, return link flairs options for a new link submission.
Otherwise, return user flair options for this subreddit.

The logged in user's flair is also returned.
Subreddit moderators may give a user by

```
name
```

to instead
retrieve that user's flair.

is\_newlink


boolean value


link


a fullname of a link


name


a user by name

### POST [/r/subreddit]/api/flairtemplatemodflair

api\_type


the string


css\_class


a valid subreddit image name


flair\_template\_id

flair\_type


one of (


text


a string no longer than 64 characters


text\_editable


boolean value


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/flairtemplate\_v2modflair

Create or update a flair template.

This new endpoint is primarily used for the redesign.

allowable\_content


one of (


api\_type


the string


background\_color


a 6-digit rgb hex color, e.g.


css\_class


a valid subreddit image name


flair\_template\_id

flair\_type


one of (


max\_emojis


an integer between 1 and 10 (default: 10)


mod\_only


boolean value


override\_css

text


a string no longer than 64 characters


text\_color


one of (


text\_editable


boolean value


uh / X-Modhash header


a modhash

### GET [/r/subreddit]/api/link\_flairflair

Return list of available link flair for the current subreddit.

Will not return flair if the user cannot set their own link flair and they are not a moderator that can set flair.

### GET [/r/subreddit]/api/link\_flair\_v2flair

Return list of available link flair for the current subreddit.

Will not return flair if the user cannot set their own link flair and they are not a moderator that can set flair.

### POST [/r/subreddit]/api/selectflairflair

api\_type


the string


background\_color


a 6-digit rgb hex color, e.g.


css\_class


a valid subreddit image name


flair\_template\_id

link


a fullname of a link


name


a user by name


return\_rtson


[all|only|none]: "all" saves attributes and returns rtjson "only" only returns rtjson"none" only saves attributes


text


a string no longer than 64 characters


text\_color


one of (


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/setflairenabledflair

api\_type


the string


flair\_enabled


boolean value


uh / X-Modhash header


a modhash

### GET [/r/subreddit]/api/user\_flairflair

Return list of available user flair for the current subreddit.

Will not return flair if flair is disabled on the subreddit, the user cannot set their own flair, or they are not a moderator that can set flair.

### GET [/r/subreddit]/api/user\_flair\_v2flair

Return list of available user flair for the current subreddit.

If user is not a mod of the subreddit, this endpoint filters out mod\_only templates.

## links & comments

### POST /api/commentany

Submit a new comment or reply to a message.

```
parent
```

is the fullname of the thing being replied to. Its value
changes the kind of object created by this request:

* the fullname of a Link: a top-level comment in that Link's thread. (requires

  ```
  submit
  ```

  scope)
* the fullname of a Comment: a comment reply to that comment. (requires

  ```
  submit
  ```

  scope)
* the fullname of a Message: a message reply to that message. (requires

  ```
  privatemessages
  ```

  scope)

```
text
```

should be the raw markdown body of the comment or message.

To start a new message thread, use /api/compose.

api\_type


the string


recaptcha\_token


a string


return\_rtjson


boolean value


richtext\_json


JSON data


text


raw markdown text


thing\_id


fullname of parent thing


uh / X-Modhash header


a modhash


video\_poster\_url


a string

### POST /api/deledit

### POST /api/editusertextedit

### POST /api/follow\_postsubscribe

### POST /api/hidereport

Hide a link.

This removes it from the user's default view of subreddit listings.

See also: /api/unhide.

id


A comma-separated list of link fullnames


uh / X-Modhash header


a modhash

### GET [/r/subreddit]/api/inforead

Return a listing of things specified by their fullnames.

Only Links, Comments, and Subreddits are allowed.

id


A comma-separated list of thing fullnames


sr\_name


comma-delimited list of subreddit names


url


a valid URL

### POST /api/lockmodposts

Lock a link or comment.

Prevents a post or new child comments from receiving new comments.

See also: /api/unlock.

id


fullname of a thing


uh / X-Modhash header


a modhash

### POST /api/marknsfwmodposts

Mark a link NSFW.

See also: /api/unmarknsfw.

id


fullname of a thing


uh / X-Modhash header


a modhash

### GET /api/morechildrenread

Retrieve additional comments omitted from a base comment tree.

When a comment tree is rendered, the most relevant comments are selected for display first. Remaining comments are stubbed out with "MoreComments" links. This API call is used to retrieve the additional comments represented by those stubs, up to 100 at a time.

The two core parameters required are

```
link
```

and

```
children
```

.

```
link
```

is
the fullname of the link whose comments are being fetched.

```
children
```

is a comma-delimited list of comment ID36s that need to be fetched.

If

```
id
```

is passed, it should be the ID of the MoreComments object this
call is replacing. This is needed only for the HTML UI's purposes and
is optional otherwise.

NOTE: you may only make one request at a time to this API endpoint. Higher concurrency will result in an error being returned.

If

```
limit_children
```

is True, only return the children requested.

```
depth
```

is the maximum depth of subtrees in the thread.

api\_type


the string


children

depth


(optional) an integer


id


(optional) id of the associated MoreChildren object


limit\_children


boolean value


link\_id


fullname of a link


sort


one of (

### POST /api/reportreport

Report a link, comment or message. Reporting a thing brings it to the attention of the subreddit's moderators. Reporting a message sends it to a system for admin review. For links and comments, the thing is implicitly hidden as well (see /api/hide for details).

See /r/{subreddit}/about/rules for
for more about subreddit rules, and /r/{subreddit}/about
for more about

```
free_form_reports
```

.

additional\_info


a string no longer than 2000 characters


api\_type


the string


custom\_text


a string no longer than 2000 characters


from\_help\_desk


boolean value


from\_modmail


boolean value


modmail\_conv\_id


base36 modmail conversation id


other\_reason


a string no longer than 100 characters


reason


a string no longer than 100 characters


rule\_reason


a string no longer than 100 characters


site\_reason


a string no longer than 100 characters


sr\_name


a string no longer than 1000 characters


thing\_id


fullname of a thing


uh / X-Modhash header


a modhash


usernames


A comma-separated list of items

### POST /api/savesave

Save a link or comment.

Saved things are kept in the user's saved listing for later perusal.

See also: /api/unsave.

category


a category name


id


fullname of a thing


uh / X-Modhash header


a modhash

### GET /api/saved\_categoriessave

Get a list of categories in which things are currently saved.

See also: /api/save.

### POST /api/sendrepliesedit

### POST /api/set\_contest\_modemodposts

Set or unset "contest mode" for a link's comments.

```
state
```

is a boolean that indicates whether you are enabling or
disabling contest mode - true to enable, false to disable.

api\_type


the string


id

state


boolean value


uh / X-Modhash header


a modhash

### POST /api/set\_subreddit\_stickymodposts

Set or unset a Link as the sticky in its subreddit.

```
state
```

is a boolean that indicates whether to sticky or unsticky
this post - true to sticky, false to unsticky.

The

```
num
```

argument is optional, and only used when stickying a post.
It allows specifying a particular "slot" to sticky the post into, and
if there is already a post stickied in that slot it will be replaced.
If there is no post in the specified slot to replace, or

```
num
```

is None,
the bottom-most slot will be used.

api\_type


the string


id

num


an integer between 1 and 4


state


boolean value


to\_profile


boolean value


uh / X-Modhash header


a modhash

### POST /api/set\_suggested\_sortmodposts

Set a suggested sort for a link.

Suggested sorts are useful to display comments in a certain preferred way for posts. For example, casual conversation may be better sorted by new by default, or AMAs may be sorted by Q&A. A sort of an empty string clears the default sort.

api\_type


the string


id

sort


one of (


uh / X-Modhash header


a modhash

### POST /api/store\_visitssave

Requires a subscription to reddit premium

links


A comma-separated list of link fullnames


uh / X-Modhash header


a modhash

### POST /api/submitsubmit

Submit a link to a subreddit.

Submit will create a link or self-post in the subreddit

```
sr
```

with the
title

```
title
```

. If

```
kind
```

is

```
"link"
```

, then

```
url
```

is expected to be a
valid URL to link to. Otherwise,

```
text
```

, if present, will be the
body of the self-post unless

```
richtext_json
```

is present, in which case
it will be converted into the body of the self-post. An error is thrown
if both

```
text
```

and

```
richtext_json
```

are present.

```
extension
```

is used for determining which view-type (e.g.

```
json
```

,

```
compact
```

etc.) to use for the redirect that is generated after submit.

ad


boolean value


api\_type


the string


app

collection\_id


(beta) the UUID of a collection


extension


extension used for redirects


flair\_id


a string no longer than 36 characters


flair\_text


a string no longer than 64 characters


g-recaptcha-response

kind


one of (


nsfw


boolean value


post\_set\_default\_post\_id


a string


post\_set\_id


a string


recaptcha\_token


a string


resubmit


boolean value


richtext\_json


JSON data


sendreplies


boolean value


spoiler


boolean value


sr


subreddit name


text


raw markdown text


title


title of the submission. up to 300 characters long


uh / X-Modhash header


a modhash


url


a valid URL


video\_poster\_url


a valid URL

### POST /api/unhidereport

### POST /api/unlockmodposts

### POST /api/unmarknsfwmodposts

Remove the NSFW marking from a link.

See also: /api/marknsfw.

id


fullname of a thing


uh / X-Modhash header


a modhash

### POST /api/unsavesave

### POST /api/votevote

Cast a vote on a thing.

```
id
```

should be the fullname of the Link or Comment to vote on.

```
dir
```

indicates the direction of the vote. Voting

```
1
```

is an upvote,

```
-1
```

is a downvote, and

```
0
```

is equivalent to "un-voting" by clicking
again on a highlighted arrow.

Note: votes must be cast by humans. That is, API clients proxying a human's action one-for-one are OK, but bots deciding how to vote on content or amplifying a human's vote are not. See the reddit rules for more details on what constitutes vote cheating.

dir


vote direction. one of (1, 0, -1)


id

uh / X-Modhash header


a modhash

## listings

### GET /bestreadrss support

### GET /by\_id/namesread

Get a listing of links by fullname.

```
names
```

is a list of fullnames for links separated by commas or spaces.

names


A comma-separated list of link fullnames

### GET [/r/subreddit]/comments/articlereadrss support

Get the comment tree for a given Link

```
article
```

.

If supplied,

```
comment
```

is the ID36 of a comment in the comment tree for

```
article
```

. This comment will be the (highlighted) focal point of the
returned view and

```
context
```

will be the number of parents shown.

```
depth
```

is the maximum depth of subtrees in the thread.

```
limit
```

is the maximum number of comments to return.

See also: /api/morechildren and /api/comment.

article


ID36 of a link


comment


(optional) ID36 of a comment


context


an integer between 0 and 8


depth


(optional) an integer


limit


(optional) an integer


showedits


boolean value


showmedia


boolean value


showmore


boolean value


showtitle


boolean value


sort


one of (


sr\_detail


(optional) expand subreddits


theme


one of (


threaded


boolean value


truncate


an integer between 0 and 50

### GET /duplicates/articlereadrss support

Return a list of other submissions of the same URL

This endpoint is a listing.

after


fullname of a thing


article


The base 36 ID of a Link


before


fullname of a thing


count


a positive integer (default: 0)


crossposts\_only


boolean value


limit


the maximum number of items desired (default: 25, maximum: 100)


show


(optional) the string


sort


one of (


sr


subreddit name


sr\_detail


(optional) expand subreddits

### GET [/r/subreddit]/hotreadrss support

This endpoint is a listing.

g


one of (


after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


show


(optional) the string


sr\_detail


(optional) expand subreddits

### GET [/r/subreddit]/newreadrss support

### GET [/r/subreddit]/risingreadrss support

### GET [/r/subreddit]/sortreadrss support

* → [/r/subreddit]/top
* → [/r/subreddit]/controversial

## live threads

Real-time updates on reddit.

In addition to the standard reddit API, WebSockets play a huge role in reddit live. Receiving push notification of changes to the thread via websockets is much better than polling the thread repeatedly.

To connect to the websocket server, fetch
/live/thread/about.json and get the

```
websocket_url
```

field. The websocket URL expires after a period of time; if it
does, fetch a new one from that endpoint.

Once connected to the socket, a variety of messages can come in. All messages
will be in text frames containing a JSON object with two keys:

```
type
```

and

```
payload
```

. Live threads can send messages with many

```
type
```

s:

* ```
  update
  ```

  - a new update has been posted in the thread. the

  ```
  payload
  ```

  contains the JSON representation of the update.
* ```
  activity
  ```

  - periodic update of the viewer counts for the thread.
* ```
  settings
  ```

  - the thread's settings have changed. the

  ```
  payload
  ```

  is an object with each key being a property of the thread (as in

  ```
  about.json
  ```

  ) and its new value.
* ```
  delete
  ```

  - an update has been deleted (removed from the thread). the

  ```
  payload
  ```

  is the ID of the deleted update.
* ```
  strike
  ```

  - an update has been stricken (marked incorrect and crossed out). the

  ```
  payload
  ```

  is the ID of the stricken update.
* ```
  embeds_ready
  ```

  - a previously posted update has been parsed and embedded media is available for it now. the

  ```
  payload
  ```

  contains a

  ```
  liveupdate_id
  ```

  and list of

  ```
  embeds
  ```

  to add to it.
* ```
  complete
  ```

  - the thread has been marked complete. no further updates will be sent.

See /r/live for more information.

### GET /api/live/by\_id/namesread

Get a listing of live events by id.

names


a comma-delimited list of live thread fullnames or IDs

### POST /api/live/createsubmit

Create a new live thread.

Once created, the initial settings can be modified with /api/live/thread/edit and new updates can be posted with /api/live/thread/update.

api\_type


the string


description


raw markdown text


nsfw


boolean value


resources


raw markdown text


title


a string no longer than 120 characters


uh / X-Modhash header


a modhash

### GET /api/live/happening\_nowread

Get some basic information about the currently featured live thread.

Returns an empty 204 response for api requests if no thread is currently featured.

See also: /api/live/thread/about.

show\_announcements


boolean value

### POST /api/live/thread/accept\_contributor\_invitelivemanage

Accept a pending invitation to contribute to the thread.

See also: /api/live/thread/leave\_contributor.

api\_type


the string


uh / X-Modhash header


a modhash

### POST /api/live/thread/close\_threadlivemanage

Permanently close the thread, disallowing future updates.

Requires the

```
close
```

permission for this thread.

api\_type


the string


uh / X-Modhash header


a modhash

### POST /api/live/thread/delete\_updateedit

Delete an update from the thread.

Requires that specified update must have been authored by the user or
that you have the

```
edit
```

permission for this thread.

See also: /api/live/thread/update.

api\_type


the string


id


the ID of a single update. e.g.


uh / X-Modhash header


a modhash

### POST /api/live/thread/editlivemanage

Configure the thread.

Requires the

```
settings
```

permission for this thread.

See also: /live/thread/about.json.

api\_type


the string


description


raw markdown text


nsfw


boolean value


resources


raw markdown text


title


a string no longer than 120 characters


uh / X-Modhash header


a modhash

### POST /api/live/thread/hide\_discussionlivemanage

Hide a linked comment thread from the discussions sidebar and listing.

Requires the

```
discussions
```

permission for this thread.

See also: /api/live/thread/unhide\_discussion.

api\_type


the string


link


The base 36 ID of a Link


uh / X-Modhash header


a modhash

### POST /api/live/thread/invite\_contributorlivemanage

Invite another user to contribute to the thread.

Requires the

```
manage
```

permission for this thread. If the recipient
accepts the invite, they will be granted the permissions specified.

See also: /api/live/thread/accept\_contributor\_invite, and /api/live/thread/rm\_contributor\_invite.

api\_type


the string


name


the name of an existing user


permissions


permission description e.g.


type


one of (


uh / X-Modhash header


a modhash

### POST /api/live/thread/leave\_contributorlivemanage

Abdicate contributorship of the thread.

See also: /api/live/thread/accept\_contributor\_invite, and /api/live/thread/invite\_contributor.

api\_type


the string


uh / X-Modhash header


a modhash

### POST /api/live/thread/reportreport

Report the thread for violating the rules of reddit.

api\_type


the string


type


one of (


uh / X-Modhash header


a modhash

### POST /api/live/thread/rm\_contributorlivemanage

Revoke another user's contributorship.

Requires the

```
manage
```

permission for this thread.

See also: /api/live/thread/invite\_contributor.

api\_type


the string


id


fullname of a account


uh / X-Modhash header


a modhash

### POST /api/live/thread/rm\_contributor\_invitelivemanage

Revoke an outstanding contributor invite.

Requires the

```
manage
```

permission for this thread.

See also: /api/live/thread/invite\_contributor.

api\_type


the string


id


fullname of a account


uh / X-Modhash header


a modhash

### POST /api/live/thread/set\_contributor\_permissionslivemanage

Change a contributor or contributor invite's permissions.

Requires the

```
manage
```

permission for this thread.

See also: /api/live/thread/invite\_contributor and /api/live/thread/rm\_contributor.

api\_type


the string


name


the name of an existing user


permissions


permission description e.g.


type


one of (


uh / X-Modhash header


a modhash

### POST /api/live/thread/strike\_updateedit

Strike (mark incorrect and cross out) the content of an update.

Requires that specified update must have been authored by the user or
that you have the

```
edit
```

permission for this thread.

See also: /api/live/thread/update.

api\_type


the string


id


the ID of a single update. e.g.


uh / X-Modhash header


a modhash

### POST /api/live/thread/unhide\_discussionlivemanage

Unhide a linked comment thread from the discussions sidebar and listing..

Requires the

```
discussions
```

permission for this thread.

See also: /api/live/thread/hide\_discussion.

api\_type


the string


link


The base 36 ID of a Link


uh / X-Modhash header


a modhash

### POST /api/live/thread/updatesubmit

Post an update to the thread.

Requires the

```
update
```

permission for this thread.

See also: /api/live/thread/strike\_update, and /api/live/thread/delete\_update.

api\_type


the string


body


raw markdown text


uh / X-Modhash header


a modhash

### GET /live/threadreadrss support

Get a list of updates posted in this thread.

See also: /api/live/thread/update.

This endpoint is a listing.

after


the ID of a single update. e.g.


before


the ID of a single update. e.g.


count


a positive integer (default: 0)


is\_embed


(internal use only)


limit


the maximum number of items desired (default: 25, maximum: 100)


stylesr


subreddit name

### GET /live/thread/aboutread

Get some basic information about the live thread.

See also: /api/live/thread/edit.

### GET /live/thread/contributorsread

Get a list of users that contribute to this thread.

See also: /api/live/thread/invite\_contributor, and /api/live/thread/rm\_contributor.

### GET /live/thread/discussionsreadrss support

Get a list of reddit submissions linking to this thread.

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


show


(optional) the string


sr\_detail


(optional) expand subreddits

## private messages

### POST /api/composeprivatemessages

Handles message composition under /message/compose.

api\_type


the string


from\_sr


subreddit name


g-recaptcha-response

subject


a string no longer than 100 characters


text


raw markdown text


to


the name of an existing user


uh / X-Modhash header


a modhash

### POST /api/del\_msgprivatemessages

### POST /api/read\_all\_messagesprivatemessages

Queue up marking all messages for a user as read.

This may take some time, and returns 202 to acknowledge acceptance of the request.

filter\_types


A comma-separated list of items


uh / X-Modhash header


a modhash

### POST /api/read\_messageprivatemessages

### GET /message/whereprivatemessagesrss support

* → /message/inbox
* → /message/unread
* → /message/sent

This endpoint is a listing.

mark


one of (


max\_replies


the maximum number of items desired (default: 0, maximum: 300)


mid

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


show


(optional) the string


sr\_detail


(optional) expand subreddits

## misc

### GET /api/v1/scopesany

Retrieve descriptions of reddit's OAuth2 scopes.

If no scopes are given, information on all scopes are returned.

Invalid scope(s) will result in a 400 error with body that indicates the invalid scope(s).

scopes


(optional) An OAuth2 scope string

## moderation

### GET [/r/subreddit]/about/logmodlogrss support

Get a list of recent moderation actions.

Moderator actions taken within a subreddit are logged. This listing is a view of that log with various filters to aid in analyzing the information.

The optional

```
mod
```

parameter can be a comma-delimited list of moderator
names to restrict the results to, or the string

```
a
```

to restrict the
results to admin actions taken within the subreddit.

The

```
type
```

parameter is optional and if sent limits the log entries
returned to only those of the type specified.

This endpoint is a listing.

after


a ModAction ID


before


a ModAction ID


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 500)


mod


(optional) a moderator filter


show


(optional) the string


sr\_detail


(optional) expand subreddits


type


one of (

### GET [/r/subreddit]/about/locationread

* → [/r/subreddit]/about/reports
* → [/r/subreddit]/about/spam
* → [/r/subreddit]/about/modqueue
* → [/r/subreddit]/about/unmoderated
* → [/r/subreddit]/about/edited

Return a listing of posts relevant to moderators.

* reports: Things that have been reported.
* spam: Things that have been marked as spam or otherwise removed.
* modqueue: Things requiring moderator review, such as reported things and items caught by the spam filter.
* unmoderated: Things that have yet to be approved/removed by a mod.
* edited: Things that have been edited recently.

Requires the "posts" moderator permission for the subreddit.

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


location

only


one of (


show


(optional) the string


sr\_detail


(optional) expand subreddits

### POST [/r/subreddit]/api/accept\_moderator\_invitemodself

Accept an invite to moderate the specified subreddit.

The authenticated user must have been invited to moderate the subreddit by one of its current moderators.

See also: /api/friend and /subreddits/mine.

api\_type


the string


uh / X-Modhash header


a modhash

### POST /api/approvemodposts

Approve a link or comment.

If the thing was removed, it will be re-inserted into appropriate listings. Any reports on the approved thing will be discarded.

See also: /api/remove.

id


fullname of a thing


uh / X-Modhash header


a modhash

### POST /api/distinguishmodposts

Distinguish a thing's author with a sigil.

This can be useful to draw attention to and confirm the identity of the user in the context of a link or comment of theirs. The options for distinguish are as follows:

* ```
  yes
  ```

  - add a moderator distinguish (

  ```
  [M]
  ```

  ). only if the user is a moderator of the subreddit the thing is in.
* ```
  no
  ```

  - remove any distinguishes.
* ```
  admin
  ```

  - add an admin distinguish (

  ```
  [A]
  ```

  ). admin accounts only.
* ```
  special
  ```

  - add a user-specific distinguish. depends on user.

The first time a top-level comment is moderator distinguished, the author of the link the comment is in reply to will get a notification in their inbox.

```
sticky
```

is a boolean flag for comments, which will stick the
distingushed comment to the top of all comments threads. If a comment
is marked sticky, it will override any other stickied comment for that
link (as only one comment may be stickied at a time.) Only top-level
comments may be stickied.

api\_type


the string


how


one of (


id


fullname of a thing


sticky


boolean value


uh / X-Modhash header


a modhash

### POST /api/ignore\_reportsmodposts

Prevent future reports on a thing from causing notifications.

Any reports made about a thing after this flag is set on it will not cause notifications or make the thing show up in the various moderation listings.

See also: /api/unignore\_reports.

id


fullname of a thing


uh / X-Modhash header


a modhash

### POST /api/leavecontributormodself

Abdicate approved user status in a subreddit.

See also: /api/friend.

id


fullname of a thing


uh / X-Modhash header


a modhash

### POST /api/leavemoderatormodself

Abdicate moderator status in a subreddit.

See also: /api/friend.

id


fullname of a thing


uh / X-Modhash header


a modhash

### POST /api/removemodposts

Remove a link, comment, or modmail message.

If the thing is a link, it will be removed from all subreddit listings. If the thing is a comment, it will be redacted and removed from all subreddit comment listings.

See also: /api/approve.

id


fullname of a thing


spam


boolean value


uh / X-Modhash header


a modhash

### POST /api/show\_commentmodposts

### POST /api/snooze\_reportsmodposts

Prevent future reports on a thing from causing notifications.

For users who reported this thing (post, comment, etc) with the given report reason, reports from those users in the next 7 days will not be escalated to moderators. See also: /api/unsnooze\_reports.

id


fullname of a thing


reason

uh / X-Modhash header


a modhash

### POST /api/unignore\_reportsmodposts

Allow future reports on a thing to cause notifications.

See also: /api/ignore\_reports.

id


fullname of a thing


uh / X-Modhash header


a modhash

### POST /api/unsnooze\_reportsmodposts

For users whose reports were snoozed (see /api/snooze\_reports), to go back to escalating future reports from those users.

id


fullname of a thing


reason

uh / X-Modhash header


a modhash

### POST /api/update\_crowd\_control\_levelmodposts

### GET [/r/subreddit]/stylesheetmodconfig

Redirect to the subreddit's stylesheet if one exists.

See also: /api/subreddit\_stylesheet.

## new modmail

### POST /api/mod/bulk\_readmodmail

Marks all conversations read for a particular conversation state within the passed list of subreddits.

entity


comma-delimited list of subreddit names


state


one of (

### GET /api/mod/conversationsmodmail

Get conversations for a logged in user or subreddits

after


A Modmail Conversation ID, in the form ModmailConversation\_<id>


entity


comma-delimited list of subreddit names


limit


an integer between 1 and 100 (default: 25)


sort


one of (


state


one of (

### POST /api/mod/conversationsmodmail

Creates a new conversation for a particular SR.

This endpoint will create a ModmailConversation object as well as the first ModmailMessage within the ModmailConversation object.

A note on

```
to
```

:

The

```
to
```

field for this endpoint is somewhat confusing. It can be:

* A User, passed like "username" or "u/username"
* A Subreddit, passed like "r/subreddit"
* null, meaning an internal moderator discussion

In this way

```
to
```

is a bit of a misnomer in modmail conversations. What
it really means is the participant of the conversation who is not a mod
of the subreddit.

body


raw markdown text


isAuthorHidden


boolean value


srName


subreddit name


subject


a string no longer than 100 characters


to


Modmail conversation recipient fullname

### GET /api/mod/conversations/:conversation\_idmodmail

Returns all messages, mod actions and conversation metadata for a given conversation id

conversation\_id


A Modmail Conversation ID, in the form ModmailConversation\_<id>


markRead


boolean value

### POST /api/mod/conversations/:conversation\_idmodmail

Creates a new message for a particular conversation.

body


raw markdown text


conversation\_id


A Modmail Conversation ID, in the form ModmailConversation\_<id>


isAuthorHidden


boolean value


isInternal


boolean value

### POST /api/mod/conversations/:conversation\_id/approvemodmail

Approve the non mod user associated with a particular conversation.

conversation\_id


base36 modmail conversation id

### POST /api/mod/conversations/:conversation\_id/archivemodmail

Marks a conversation as archived.

conversation\_id


A Modmail Conversation ID, in the form ModmailConversation\_<id>

### POST /api/mod/conversations/:conversation\_id/disapprovemodmail

Disapprove the non mod user associated with a particular conversation.

conversation\_id


base36 modmail conversation id

### DELETE /api/mod/conversations/:conversation\_id/highlightmodmail

Removes a highlight from a conversation.

conversation\_id


A Modmail Conversation ID, in the form ModmailConversation\_<id>

### POST /api/mod/conversations/:conversation\_id/highlightmodmail

Marks a conversation as highlighted.

conversation\_id


A Modmail Conversation ID, in the form ModmailConversation\_<id>

### POST /api/mod/conversations/:conversation\_id/mutemodmail

Mutes the non mod user associated with a particular conversation.

conversation\_id


base36 modmail conversation id


num\_hours


one of (

### POST /api/mod/conversations/:conversation\_id/temp\_banmodmail

Temporary ban (switch from permanent to temporary ban) the non mod user associated with a particular conversation.

conversation\_id


base36 modmail conversation id


duration


an integer between 1 and 999

### POST /api/mod/conversations/:conversation\_id/unarchivemodmail

Marks conversation as unarchived.

conversation\_id


A Modmail Conversation ID, in the form ModmailConversation\_<id>

### POST /api/mod/conversations/:conversation\_id/unbanmodmail

Unban the non mod user associated with a particular conversation.

conversation\_id


base36 modmail conversation id

### POST /api/mod/conversations/:conversation\_id/unmutemodmail

Unmutes the non mod user associated with a particular conversation.

conversation\_id


base36 modmail conversation id

### POST /api/mod/conversations/readmodmail

Marks a conversations as read for the user.

conversationIds


A comma-separated list of items

### GET /api/mod/conversations/subredditsmodmail

Returns a list of srs that the user moderates with mail permission

### POST /api/mod/conversations/unreadmodmail

Marks conversations as unread for the user.

conversationIds


A comma-separated list of items

### GET /api/mod/conversations/unread/countmodmail

Endpoint to retrieve the unread conversation count by conversation state.

## modnote

### DELETE /api/mod/notesmodnote

Delete a mod user note where type=NOTE.

Parameters should be passed as query parameters.

note\_id


a unique ID for the note to be deleted (should have a ModNote\_ prefix)


subreddit


subreddit name


user


account username

### GET /api/mod/notesmodnote

Get mod notes for a specific user in a given subreddit.

before


(optional) an encoded string used for pagination with mod notes


filter


(optional) one of (NOTE, APPROVAL, REMOVAL, BAN, MUTE, INVITE, SPAM, CONTENT\_CHANGE, MOD\_ACTION, ALL), to be used for querying specific types of mod notes (default: all)


limit


(optional) the number of mod notes to return in the response payload (default: 25, max: 100)'}


subreddit


subreddit name


user


account username

### POST /api/mod/notesmodnote

Create a mod user note where type=NOTE.

label


(optional) one of (BOT\_BAN, PERMA\_BAN, BAN, ABUSE\_WARNING, SPAM\_WARNING, SPAM\_WATCH, SOLID\_CONTRIBUTOR, HELPFUL\_USER, USER\_SUMMARY)


note


Content of the note, should be a string with a maximum character limit of 250


reddit\_id


(optional) a fullname of a comment or post (should have either a t1 or t3 prefix)


subreddit


subreddit name


user


account username

### GET /api/mod/notes/recentmodnote

Fetch the most recent notes written by a moderator

Both parameters should be comma separated lists of equal lengths. The first subreddit will be paired with the first account to represent a query for a mod written note for that account in that subreddit and so forth for all subsequent pairs of subreddits and accounts. This request accepts up to 500 pairs of subreddit names and usernames. Parameters should be passed as query parameters.

The response will be a list of mod notes in the order that subreddits and accounts were given. If no note exist for a given subreddit/account pair, then null will take its place in the list.

subreddits


a comma delimited list of subreddits by name


users


a comma delimited list of usernames

## multis

### POST /api/multi/copysubscribe

Copy a multi.

Responds with 409 Conflict if the target already exists.

A "copied from ..." line will automatically be appended to the description.

description\_md


raw markdown text


display\_name


a string no longer than 50 characters


expand\_srs


boolean value


from


multireddit url path


to


destination multireddit url path


uh / X-Modhash header


a modhash

### GET /api/multi/mineread

Fetch a list of multis belonging to the current user.

expand\_srs


boolean value

### GET /api/multi/user/usernameread

Fetch a list of public multis belonging to

```
username
```

expand\_srs


boolean value


username


A valid, existing reddit username

### DELETE /api/multi/multipathsubscribe

* → /api/filter/filterpath

Delete a multi.

multipath


multireddit url path


uh / X-Modhash header


a modhash


expand\_srs


boolean value

### GET /api/multi/multipathread

* → /api/filter/filterpath

Fetch a multi's data and subreddit list by name.

expand\_srs


boolean value


multipath


multireddit url path

### POST /api/multi/multipathsubscribe

* → /api/filter/filterpath

Create a multi. Responds with 409 Conflict if it already exists.

model


json data:


multipath


multireddit url path


uh / X-Modhash header


a modhash


expand\_srs


boolean value

### PUT /api/multi/multipathsubscribe

* → /api/filter/filterpath

Create or update a multi.

expand\_srs


boolean value


model


json data:


multipath


multireddit url path


uh / X-Modhash header


a modhash

### PUT /api/multi/multipath/descriptionread

Change a multi's markdown description.

model


json data:


multipath


multireddit url path


uh / X-Modhash header


a modhash

### DELETE /api/multi/multipath/r/srnamesubscribe

* → /api/filter/filterpath/r/srname

Remove a subreddit from a multi.

multipath


multireddit url path


srname


subreddit name


uh / X-Modhash header


a modhash

### GET /api/multi/multipath/r/srnameread

* → /api/filter/filterpath/r/srname

Get data about a subreddit in a multi.

multipath


multireddit url path


srname


subreddit name

### PUT /api/multi/multipath/r/srnamesubscribe

* → /api/filter/filterpath/r/srname

Add a subreddit to a multi.

model


json data:


multipath


multireddit url path


srname


subreddit name


uh / X-Modhash header


a modhash

## search

### GET [/r/subreddit]/searchreadrss support

Search links page.

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


category


a string no longer than 5 characters


count


a positive integer (default: 0)


include\_facets


boolean value


limit


the maximum number of items desired (default: 25, maximum: 100)


q


a string no longer than 512 characters


restrict\_sr


boolean value


show


(optional) the string


sort


one of (


sr\_detail


(optional) expand subreddits


t


one of (


type


(optional) comma-delimited list of result types (

## subreddits

### GET [/r/subreddit]/about/wherereadrss support

* → [/r/subreddit]/about/banned
* → [/r/subreddit]/about/muted
* → [/r/subreddit]/about/wikibanned
* → [/r/subreddit]/about/contributors
* → [/r/subreddit]/about/wikicontributors
* → [/r/subreddit]/about/moderators

### POST [/r/subreddit]/api/delete\_sr\_bannermodconfig

Remove the subreddit's custom mobile banner.

See also: /api/upload\_sr\_img.

api\_type


the string


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/delete\_sr\_headermodconfig

Remove the subreddit's custom header image.

The sitewide-default header image will be shown again after this call.

See also: /api/upload\_sr\_img.

api\_type


the string


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/delete\_sr\_iconmodconfig

Remove the subreddit's custom mobile icon.

See also: /api/upload\_sr\_img.

api\_type


the string


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/delete\_sr\_imgmodconfig

Remove an image from the subreddit's custom image set.

The image will no longer count against the subreddit's image limit. However, the actual image data may still be accessible for an unspecified amount of time. If the image is currently referenced by the subreddit's stylesheet, that stylesheet will no longer validate and won't be editable until the image reference is removed.

See also: /api/upload\_sr\_img.

api\_type


the string


img\_name


a valid subreddit image name


uh / X-Modhash header


a modhash

### GET /api/recommend/sr/srnamesread

DEPRECATED: Return subreddits recommended for the given subreddit(s).

Gets a list of subreddits recommended for

```
srnames
```

, filtering out any
that appear in the optional

```
omit
```

param.

omit


comma-delimited list of subreddit names


over\_18


boolean value


srnames


comma-delimited list of subreddit names

### GET /api/search\_reddit\_namesread

List subreddit names that begin with a query string.

Subreddits whose names begin with

```
query
```

will be returned. If

```
include_over_18
```

is false, subreddits with over-18 content
restrictions will be filtered from the results.

If

```
include_unadvertisable
```

is False, subreddits that have

```
hide_ads
```

set to True or are on the

```
anti_ads_subreddits
```

list will be filtered.

If

```
exact
```

is true, only an exact match will be returned. Exact matches
are inclusive of

```
over_18
```

subreddits, but not

```
hide_ad
```

subreddits
when

```
include_unadvertisable
```

is

```
False
```

.

exact


boolean value


include\_over\_18


boolean value


include\_unadvertisable


boolean value


query


a string up to 50 characters long, consisting of printable characters.


search\_query\_id


a uuid


typeahead\_active


boolean value or None

### POST /api/search\_reddit\_namesread

List subreddit names that begin with a query string.

Subreddits whose names begin with

```
query
```

will be returned. If

```
include_over_18
```

is false, subreddits with over-18 content
restrictions will be filtered from the results.

If

```
include_unadvertisable
```

is False, subreddits that have

```
hide_ads
```

set to True or are on the

```
anti_ads_subreddits
```

list will be filtered.

If

```
exact
```

is true, only an exact match will be returned. Exact matches
are inclusive of

```
over_18
```

subreddits, but not

```
hide_ad
```

subreddits
when

```
include_unadvertisable
```

is

```
False
```

.

exact


boolean value


include\_over\_18


boolean value


include\_unadvertisable


boolean value


query


a string up to 50 characters long, consisting of printable characters.


search\_query\_id


a uuid


typeahead\_active


boolean value or None

### POST /api/search\_subredditsread

List subreddits that begin with a query string.

Subreddits whose names begin with

```
query
```

will be returned. If

```
include_over_18
```

is false, subreddits with over-18 content
restrictions will be filtered from the results.

If

```
include_unadvertisable
```

is False, subreddits that have

```
hide_ads
```

set to True or are on the

```
anti_ads_subreddits
```

list will be filtered.

If

```
exact
```

is true, only an exact match will be returned. Exact matches
are inclusive of

```
over_18
```

subreddits, but not

```
hide_ad
```

subreddits
when

```
include_unadvertisable
```

is

```
False
```

.

exact


boolean value


include\_over\_18


boolean value


include\_unadvertisable


boolean value


query


a string up to 50 characters long, consisting of printable characters.


search\_query\_id


a uuid


typeahead\_active


boolean value or None

### POST /api/site\_adminmodconfig

Create or configure a subreddit.

If

```
sr
```

is specified, the request will attempt to modify the specified
subreddit. If not, a subreddit with name

```
name
```

will be created.

This endpoint expects all values to be supplied on every request. If modifying a subset of options, it may be useful to get the current settings from /about/edit.json first.

For backwards compatibility,

```
description
```

is the sidebar text and

```
public_description
```

is the publicly visible subreddit description.

Most of the parameters for this endpoint are identical to options visible in the user interface and their meanings are best explained there.

See also: /about/edit.json.

accept\_followers


boolean value


admin\_override\_spam\_comments


boolean value


admin\_override\_spam\_links


boolean value


admin\_override\_spam\_selfposts


boolean value


all\_original\_content


boolean value


allow\_chat\_post\_creation


boolean value


allow\_discovery


boolean value


allow\_galleries


boolean value


allow\_images


boolean value


allow\_polls


boolean value


allow\_post\_crossposts


boolean value


allow\_prediction\_contributors


boolean value


allow\_predictions


boolean value


allow\_predictions\_tournament


boolean value


allow\_talks


boolean value


allow\_top


boolean value


allow\_videos


boolean value


api\_type


the string


collapse\_deleted\_comments


boolean value


comment\_contribution\_settings


json data:


comment\_score\_hide\_mins


an integer between 0 and 1440 (default: 0)


crowd\_control\_chat\_level


an integer between 0 and 3


crowd\_control\_filter


boolean value


crowd\_control\_level


an integer between 0 and 3


crowd\_control\_mode


boolean value


crowd\_control\_post\_level


an integer between 0 and 3


description


raw markdown text


disable\_contributor\_requests


boolean value


exclude\_banned\_modqueue


boolean value


free\_form\_reports


boolean value


g-recaptcha-response

hateful\_content\_threshold\_abuse


an integer between 0 and 3


hateful\_content\_threshold\_identity


an integer between 0 and 3


header-title


a string no longer than 500 characters


hide\_ads


boolean value


key\_color


a 6-digit rgb hex color, e.g.


link\_type


one of (


modmail\_harassment\_filter\_enabled


boolean value


name


subreddit name


new\_pinned\_post\_pns\_enabled


boolean value


original\_content\_tag\_enabled


boolean value


over\_18


boolean value


prediction\_leaderboard\_entry\_type


an integer between 0 and 2


public\_description


raw markdown text


restrict\_commenting


boolean value


restrict\_posting


boolean value


should\_archive\_posts


boolean value


show\_media


boolean value


show\_media\_preview


boolean value


spam\_comments


one of (


spam\_links


one of (


spam\_selfposts


one of (


spoilers\_enabled


boolean value


sr


fullname of a thing


submit\_link\_label


a string no longer than 60 characters


submit\_text


raw markdown text


submit\_text\_label


a string no longer than 60 characters


subreddit\_discovery\_settings


json data:


suggested\_comment\_sort


one of (


title


a string no longer than 100 characters


toxicity\_threshold\_chat\_level


an integer between 0 and 1


type


one of (


uh / X-Modhash header


a modhash


user\_flair\_pns\_enabled


boolean value


welcome\_message\_enabled


boolean value


welcome\_message\_text


raw markdown text


wiki\_edit\_age


an integer between 0 and 36600 (default: 0)


wiki\_edit\_karma


an integer between 0 and 1000000000 (default: 0)


wikimode


one of (

### GET [/r/subreddit]/api/submit\_textsubmit

Get the submission text for the subreddit.

This text is set by the subreddit moderators and intended to be displayed on the submission form.

See also: /api/site\_admin.

### GET /api/subreddit\_autocompleteread

Return a list of subreddits and data for subreddits whose names start with 'query'.

Uses typeahead endpoint to recieve the list of subreddits names. Typeahead provides exact matches, typo correction, fuzzy matching and boosts subreddits to the top that the user is subscribed to.

include\_over\_18


boolean value


include\_profiles


boolean value


query


a string up to 25 characters long, consisting of printable characters.

### GET /api/subreddit\_autocomplete\_v2read

include\_over\_18


boolean value


include\_profiles


boolean value


limit


an integer between 1 and 10 (default: 5)


query


a string up to 25 characters long, consisting of printable characters.


search\_query\_id


a uuid


typeahead\_active


boolean value or None

### POST [/r/subreddit]/api/subreddit\_stylesheetmodconfig

Update a subreddit's stylesheet.

```
op
```

should be

```
save
```

to update the contents of the stylesheet.

api\_type


the string


op


one of (


reason


a string up to 256 characters long, consisting of printable characters.


stylesheet\_contents


the new stylesheet content


uh / X-Modhash header


a modhash

### POST /api/subscribesubscribe

Subscribe to or unsubscribe from a subreddit.

To subscribe,

```
action
```

should be

```
sub
```

. To unsubscribe,

```
action
```

should
be

```
unsub
```

. The user must have access to the subreddit to be able to
subscribe to it.

The

```
skip_initial_defaults
```

param can be set to True to prevent
automatically subscribing the user to the current set of defaults
when they take their first subscription action. Attempting to set it
for an unsubscribe action will result in an error.

See also: /subreddits/mine/.

action


one of (


action\_source


one of (


skip\_initial\_defaults


boolean value


sr / sr\_name


A comma-separated list of subreddit fullnames (when using the "sr" parameter), or of subreddit names (when using the "sr\_name" parameter).


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/upload\_sr\_imgmodconfig

Add or replace a subreddit image, custom header logo, custom mobile icon, or custom mobile banner.

* If the

  ```
  upload_type
  ```

  value is

  ```
  img
  ```

  , an image for use in the subreddit stylesheet is uploaded with the name specified in

  ```
  name
  ```

  .
* If the

  ```
  upload_type
  ```

  value is

  ```
  header
  ```

  then the image uploaded will be the subreddit's new logo and

  ```
  name
  ```

  will be ignored.
* If the

  ```
  upload_type
  ```

  value is

  ```
  icon
  ```

  then the image uploaded will be the subreddit's new mobile icon and

  ```
  name
  ```

  will be ignored.
* If the

  ```
  upload_type
  ```

  value is

  ```
  banner
  ```

  then the image uploaded will be the subreddit's new mobile banner and

  ```
  name
  ```

  will be ignored.

For backwards compatibility, if

```
upload_type
```

is not specified, the

```
header
```

field will be used instead:

* If the

  ```
  header
  ```

  field has value

  ```
  0
  ```

  , then

  ```
  upload_type
  ```

  is

  ```
  img
  ```

  .
* If the

  ```
  header
  ```

  field has value

  ```
  1
  ```

  , then

  ```
  upload_type
  ```

  is

  ```
  header
  ```

  .

The

```
img_type
```

field specifies whether to store the uploaded image as a
PNG or JPEG.

Subreddits have a limited number of images that can be in use at any given time. If no image with the specified name already exists, one of the slots will be consumed.

If an image with the specified name already exists, it will be replaced. This does not affect the stylesheet immediately, but will take effect the next time the stylesheet is saved.

See also: /api/delete\_sr\_img, /api/delete\_sr\_header, /api/delete\_sr\_icon, and /api/delete\_sr\_banner.

file


file upload with maximum size of 500 KiB


formid


(optional) can be ignored


header


an integer between 0 and 1


img\_type


one of


name


a valid subreddit image name


uh / X-Modhash header


a modhash


upload\_type


one of (

### GET /api/v1/subreddit/post\_requirementssubmit

Fetch moderator-designated requirements to post to the subreddit.

Moderators may enable certain restrictions, such as minimum title length, when making a submission to their subreddit.

Clients may use the values returned by this endpoint to pre-validate fields before making a request to POST /api/submit. This may allow the client to provide a better user experience to the user, for example by creating a text field in their app that does not allow the user to enter more characters than the max title length.

A non-exhaustive list of possible requirements a moderator may enable:

* ```
  body_blacklisted_strings
  ```

  : List of strings. Users may not submit posts that contain these words.
* ```
  body_restriction_policy
  ```

  : String. One of "required", "notAllowed", or "none", meaning that a self-post body is required, not allowed, or optional, respectively.
* ```
  domain_blacklist
  ```

  : List of strings. Users may not submit links to these domains
* ```
  domain_whitelist
  ```

  : List of strings. Users submissions MUST be from one of these domains
* ```
  is_flair_required
  ```

  : Boolean. If True, flair must be set at submission time.
* ```
  title_blacklisted_strings
  ```

  : List of strings. Submission titles may NOT contain any of the listed strings.
* ```
  title_required_strings
  ```

  : List of strings. Submission title MUST contain at least ONE of the listed strings.
* ```
  title_text_max_length
  ```

  : Integer. Maximum length of the title field.
* ```
  title_text_min_length
  ```

  : Integer. Minimum length of the title field.

### GET /r/subreddit/aboutread

Return information about the subreddit.

Data includes the subscriber count, description, and header image.

### GET /r/subreddit/about/editmodconfig

Get the current settings of a subreddit.

In the API, this returns the current settings of the subreddit as used by /api/site\_admin. On the HTML site, it will display a form for editing the subreddit.

created


one of (


location

### GET [/r/subreddit]/stickyread

Redirect to one of the posts stickied in the current subreddit

The "num" argument can be used to select a specific sticky, and will default to 1 (the top sticky) if not specified. Will 404 if there is not currently a sticky post in this subreddit.

num


an integer between 1 and 2 (default: 1)

### GET /subreddits/mine/wheremysubredditsrss support

* → /subreddits/mine/subscriber
* → /subreddits/mine/contributor
* → /subreddits/mine/moderator
* → /subreddits/mine/streams

Get subreddits the user has a relationship with.

The

```
where
```

parameter chooses which subreddits are returned as follows:

* ```
  subscriber
  ```

  - subreddits the user is subscribed to
* ```
  contributor
  ```

  - subreddits the user is an approved user in
* ```
  moderator
  ```

  - subreddits the user is a moderator of
* ```
  streams
  ```

  - subscribed to subreddits that contain hosted video links

See also: /api/subscribe, /api/friend, and /api/accept\_moderator\_invite.

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


show


(optional) the string


sr\_detail


(optional) expand subreddits

### GET /subreddits/searchreadrss support

Search subreddits by title and description.

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


q


a search query


search\_query\_id


a uuid


show


(optional) the string


show\_users


boolean value


sort


one of (


sr\_detail


(optional) expand subreddits


typeahead\_active


boolean value or None

### GET /subreddits/wherereadrss support

* → /subreddits/popular
* → /subreddits/new
* → /subreddits/gold
* → /subreddits/default

Get all subreddits.

The

```
where
```

parameter chooses the order in which the subreddits are
displayed.

```
popular
```

sorts on the activity of the subreddit and the
position of the subreddits can shift around.

```
new
```

sorts the subreddits
based on their creation date, newest first.

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


show


(optional) the string


sr\_detail


(optional) expand subreddits

### GET /users/searchreadrss support

Search user profiles by title and description.

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


q


a search query


search\_query\_id


a uuid


show


(optional) the string


sort


one of (


sr\_detail


(optional) expand subreddits


typeahead\_active


boolean value or None

### GET /users/wherereadrss support

* → /users/popular
* → /users/new

Get all user subreddits.

The

```
where
```

parameter chooses the order in which the subreddits are
displayed.

```
popular
```

sorts on the activity of the subreddit and the
position of the subreddits can shift around.

```
new
```

sorts the user
subreddits based on their creation date, newest first.

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


show


(optional) the string


sr\_detail


(optional) expand subreddits

## users

### POST /api/block\_useraccount

### POST [/r/subreddit]/api/friendany

Create a relationship between a user and another user or subreddit

OAuth2 use requires appropriate scope based on the 'type' of the relationship:

* moderator: Use "moderator\_invite"
* moderator\_invite:

  ```
  modothers
  ```
* contributor:

  ```
  modcontributors
  ```
* banned:

  ```
  modcontributors
  ```
* muted:

  ```
  modcontributors
  ```
* wikibanned:

  ```
  modcontributors
  ```

  and

  ```
  modwiki
  ```
* wikicontributor:

  ```
  modcontributors
  ```

  and

  ```
  modwiki
  ```
* friend: Use /api/v1/me/friends/{username}
* enemy: Use /api/block

Complement to POST\_unfriend

api\_type


the string


ban\_context


fullname of a thing


ban\_message


raw markdown text


ban\_reason


a string no longer than 100 characters


container

duration


an integer between 1 and 999


name


the name of an existing user


note


a string no longer than 300 characters


permissions

type


one of (


uh / X-Modhash header


a modhash

### POST /api/report\_userreport

Report a user. Reporting a user brings it to the attention of a Reddit admin.

details


JSON data


reason


a string no longer than 100 characters


('user',)


A valid, existing reddit username

### POST [/r/subreddit]/api/setpermissionsmodothers

api\_type


the string


name


the name of an existing user


permissions

type

uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/unfriendany

Remove a relationship between a user and another user or subreddit

The user can either be passed in by name (nuser) or by fullname (iuser). If type is friend or enemy, 'container' MUST be the current user's fullname; for other types, the subreddit must be set via URL (e.g., /r/funny/api/unfriend)

OAuth2 use requires appropriate scope based on the 'type' of the relationship:

* moderator:

  ```
  modothers
  ```
* moderator\_invite:

  ```
  modothers
  ```
* contributor:

  ```
  modcontributors
  ```
* banned:

  ```
  modcontributors
  ```
* muted:

  ```
  modcontributors
  ```
* wikibanned:

  ```
  modcontributors
  ```

  and

  ```
  modwiki
  ```
* wikicontributor:

  ```
  modcontributors
  ```

  and

  ```
  modwiki
  ```
* friend: Use /api/v1/me/friends/{username}
* enemy:

  ```
  privatemessages
  ```

Complement to POST\_friend

api\_type


the string


container

id


fullname of a thing


name


the name of an existing user


type


one of (


uh / X-Modhash header


a modhash

### GET /api/username\_availableany

Check whether a username is available for registration.

user


a valid, unused, username

### DELETE /api/v1/me/friends/usernamesubscribe

Stop being friends with a user.

id


A valid, existing reddit username

### PUT /api/v1/me/friends/usernamesubscribe

Create or update a "friend" relationship.

This operation is idempotent. It can be used to add a new friend, or update an existing friend (e.g., add/change the note on that friend)

This endpoint expects JSON data of this format

### GET /api/v1/user/username/trophiesread

Return a list of trophies for the a given user.

id


A valid, existing reddit username

### GET /user/username/aboutread

Return information about the user, including karma and gold status.

username


the name of an existing user

### GET /user/username/wherehistoryrss support

* → /user/username/overview
* → /user/username/submitted
* → /user/username/comments
* → /user/username/upvoted
* → /user/username/downvoted
* → /user/username/saved
* → /user/username/gilded

This endpoint is a listing.

context


an integer between 2 and 10


show


one of (


sort


one of (


t


one of (


type


one of (


username


the name of an existing user


after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


sr\_detail


(optional) expand subreddits

## widgets

### POST [/r/subreddit]/api/widgetstructuredstyles

Add and return a widget to the specified subreddit

Accepts a JSON payload representing the widget data to be saved. Valid payloads differ in shape based on the "kind" attribute passed on the root object, which must be a valid widget kind.

json


json data:

### DELETE [/r/subreddit]/api/widget/widget\_idstructuredstyles

Delete a widget from the specified subreddit (if it exists)

widget\_id


id of an existing widget

### PUT [/r/subreddit]/api/widget/widget\_idstructuredstyles

Update and return the data of a widget.

Accepts a JSON payload representing the widget data to be saved. Valid payloads differ in shape based on the "kind" attribute passed on the root object, which must be a valid widget kind.

json


json data:


widget\_id


a valid widget id

### POST [/r/subreddit]/api/widget\_image\_upload\_s3structuredstyles

Acquire and return an upload lease to s3 temp bucket.

The return value of this function is a json object containing credentials for uploading assets to S3 bucket, S3 url for upload request and the key to use for uploading. Using this lease the client will upload the emoji image to S3 temp bucket (included as part of the S3 URL).

This lease is used by S3 to verify that the upload is authorized.

filepath


name and extension of the image file e.g. image1.png


mimetype


mime type of the image e.g. image/png

### PATCH [/r/subreddit]/api/widget\_order/sectionstructuredstyles

Update the order of widget\_ids in the specified subreddit

json


json data:


section


one of (

### GET [/r/subreddit]/api/widgetsstructuredstyles

Return all widgets for the given subreddit

progressive\_images


boolean value

## wiki

### POST [/r/subreddit]/api/wiki/alloweditor/actmodwiki

* → [/r/subreddit]/api/wiki/alloweditor/del
* → [/r/subreddit]/api/wiki/alloweditor/add

Allow/deny

```
username
```

to edit this wiki

```
page
```

act


one of (


page


the name of an existing wiki page


uh / X-Modhash header


a modhash


username


the name of an existing user

### POST [/r/subreddit]/api/wiki/editwikiedit

Edit a wiki

```
page
```

content

page


the name of an existing page or a new page to create


previous


the starting point revision for this edit


reason


a string up to 256 characters long, consisting of printable characters.


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/wiki/hidemodwiki

Toggle the public visibility of a wiki page revision

page


the name of an existing wiki page


revision


a wiki revision ID


uh / X-Modhash header


a modhash

### POST [/r/subreddit]/api/wiki/revertmodwiki

Revert a wiki

```
page
```

to

```
revision
```

page


the name of an existing wiki page


revision


a wiki revision ID


uh / X-Modhash header


a modhash

### GET [/r/subreddit]/wiki/discussions/pagewikiread

Retrieve a list of discussions about this wiki

```
page
```

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


page


the name of an existing wiki page


show


(optional) the string


sr\_detail


(optional) expand subreddits

### GET [/r/subreddit]/wiki/revisionswikiread

### GET [/r/subreddit]/wiki/revisions/pagewikiread

Retrieve a list of revisions of this wiki

```
page
```

This endpoint is a listing.

after


fullname of a thing


before


fullname of a thing


count


a positive integer (default: 0)


limit


the maximum number of items desired (default: 25, maximum: 100)


page


the name of an existing wiki page


show


(optional) the string


sr\_detail


(optional) expand subreddits

### GET [/r/subreddit]/wiki/settings/pagemodwiki

Retrieve the current permission settings for

```
page
```

page


the name of an existing wiki page
