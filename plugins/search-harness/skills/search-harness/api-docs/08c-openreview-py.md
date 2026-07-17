---
source: OpenReview Python Client Documentation
url: https://openreview-py.readthedocs.io/en/latest/
note: official openreview-py SDK reference (use this for CLI-style API access; the api2.openreview.net REST endpoint is documented in 08-openreview.md but is sparse)
fetcher: r.jina.ai
fetched_at: 2026-05-04
---

Title: OpenReview Python Client Documentation — OpenReview Python Client 0.0.1 documentation

URL Source: https://openreview-py.readthedocs.io/en/latest/

Markdown Content:
*   [](https://openreview-py.readthedocs.io/en/latest/#)
*   OpenReview Python Client Documentation
*   [View page source](https://openreview-py.readthedocs.io/en/latest/_sources/index.rst.txt)

* * *

The OpenReview Python Client makes it easy to interact with the OpenReview REST API from the command line or a Python application. This library is the official API client created and maintained by the OpenReview Team.

## Contents[](https://openreview-py.readthedocs.io/en/latest/#contents "Link to this heading")

*   [About OpenReview](https://openreview.net/about)
*   [How to Setup](https://docs.openreview.net/getting-started/using-the-api/installing-and-instantiating-the-python-client)
*   [Package Documentation](https://openreview-py.readthedocs.io/en/latest/api.html)
    *   [Client](https://openreview-py.readthedocs.io/en/latest/api.html#module-openreview)
        *   [`Client`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.Client)
        *   [`Group`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.Group)
        *   [`Invitation`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.Invitation)
        *   [`Note`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.Note)
        *   [`Tag`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.Tag)
        *   [`Profile`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.Profile)

    *   [API 2 Client](https://openreview-py.readthedocs.io/en/latest/api.html#api-2-client)
        *   [`OpenReviewClient`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.api.OpenReviewClient)
        *   [`Group`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.api.Group)
        *   [`Invitation`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.api.Invitation)
        *   [`Note`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.api.Note)
        *   [`Edit`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.api.Edit)

    *   [Tools](https://openreview-py.readthedocs.io/en/latest/api.html#module-openreview.tools)
        *   [`concurrent_get()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.concurrent_get)
        *   [`concurrent_requests()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.concurrent_requests)
        *   [`create_profile()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.create_profile)
        *   [`datetime_millis()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.datetime_millis)
        *   [`decision_to_venue()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.decision_to_venue)
        *   [`efficient_iterget`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.efficient_iterget)
        *   [`generate_bibtex()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.generate_bibtex)
        *   [`get_all_venues()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_all_venues)
        *   [`get_comprehensive_profile_info()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_comprehensive_profile_info)
        *   [`get_conflicts()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_conflicts)
        *   [`get_current_submissions_profile_info()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_current_submissions_profile_info)
        *   [`get_group()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_group)
        *   [`get_invitation()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_invitation)
        *   [`get_neurips_profile_info()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_neurips_profile_info)
        *   [`get_note()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_note)
        *   [`get_paperhash()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_paperhash)
        *   [`get_preferred_name()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_preferred_name)
        *   [`get_profile()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_profile)
        *   [`get_profile_info()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_profile_info)
        *   [`get_profiles()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_profiles)
        *   [`get_user_hash_key()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.get_user_hash_key)
        *   [`is_accept_decision()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.is_accept_decision)
        *   [`iterget`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.iterget)
        *   [`iterget_edges()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.iterget_edges)
        *   [`iterget_grouped_edges()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.iterget_grouped_edges)
        *   [`iterget_groups()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.iterget_groups)
        *   [`iterget_invitations()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.iterget_invitations)
        *   [`iterget_messages()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.iterget_messages)
        *   [`iterget_notes()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.iterget_notes)
        *   [`iterget_references()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.iterget_references)
        *   [`iterget_tags()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.iterget_tags)
        *   [`overwrite_pdf()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.overwrite_pdf)
        *   [`percentile()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.percentile)
        *   [`post_bulk_edges()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.post_bulk_edges)
        *   [`post_bulk_tags()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.post_bulk_tags)
        *   [`recruit_reviewer()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.recruit_reviewer)
        *   [`recruit_user()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.recruit_user)
        *   [`replace_members_with_ids()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.replace_members_with_ids)
        *   [`run_once()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.run_once)
        *   [`should_match_invitation_source()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.should_match_invitation_source)
        *   [`subdomains()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.subdomains)
        *   [`timestamp_GMT()`](https://openreview-py.readthedocs.io/en/latest/api.html#openreview.tools.timestamp_GMT)

*   [Help](https://openreview-py.readthedocs.io/en/latest/help.html)

## Indices and Tables[](https://openreview-py.readthedocs.io/en/latest/#indices-and-tables "Link to this heading")

*   [Index](https://openreview-py.readthedocs.io/en/latest/genindex.html)

*   [Module Index](https://openreview-py.readthedocs.io/en/latest/py-modindex.html)
