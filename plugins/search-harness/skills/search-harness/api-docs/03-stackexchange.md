---
source: Usage of /search/advanced [GET] - 
        Stack Exchange API
url: https://api.stackexchange.com/docs/advanced-search
final_url: https://api.stackexchange.com/docs/advanced-search
language: en
fetched_at: 2026-05-04
bytes: 2587
---

# Usage of /search/advanced [GET] - 
        Stack Exchange API

> 

# Usage of /search/advanced GET

## Discussion

Searches a site for any questions which fit the given criteria.

Search criteria are expressed using the following parameters:

* `q` - a free form text parameter, will match all question properties based on an undocumented algorithm.
* `accepted` - true to return only questions with accepted answers, false to return only those without. Omit to elide constraint.
* `answers` - the minimum number of answers returned questions must have.
* `body` - text which must appear in returned questions' bodies.
* `closed` - true to return only closed questions, false to return only open ones. Omit to elide constraint.
* `migrated` - true to return only questions migrated away from a site, false to return only those not. Omit to elide constraint.
* `notice` - true to return only questions with post notices, false to return only those without. Omit to elide constraint.
* `nottagged` - a semicolon delimited list of tags, none of which will be present on returned questions.
* `tagged` - a semicolon delimited list of tags, of which at least one will be present on all returned questions.
* `title` - text which must appear in returned questions' titles.
* `user` - the id of the user who must own the questions returned.
* `url` - a url which must be contained in a post, may include a wildcard.
* `views` - the minimum number of views returned questions must have.
* `wiki` - true to return only community wiki questions, false to return only non-community wiki ones. Omit to elide constraint.

At least one additional parameter must be set if `nottagged` is set, for performance reasons.

The sorts accepted by this method operate on the following fields of the question object:

* **activity** – `last_activity_date`
* **creation** – `creation_date`
* **votes** – `score`
* **relevance** – matches the relevance tab on the site itself
  + Does not accept `min` or `max`

`activity` is the default sort.  
  
It is possible to create moderately complex queries using `sort`, `min`, `max`, `fromdate`, and `todate`.

This method returns a list of questions.

## Try It

Stack Overflow [edit]
stackoverflow
https://stackoverflow.com

https://stackoverflow.com/oauth/dialog?client\_id=1&key=U4DMV\*8nvpm3EOpvf69Rxw((&redirect\_uri=https%3a%2f%2fapi.stackexchange.com%2fdocs%2foauth\_landing 

U4DMV\*8nvpm3EOpvf69Rxw((

link

default filter [edit] ▼

filter ▲

show [n] types not returned by /search/advanced GET

make unsafe (?)

unselect all

cancel

site design / logo © 2026 Stack Exchange, Inc; user contributions licensed under CC BY-SA
