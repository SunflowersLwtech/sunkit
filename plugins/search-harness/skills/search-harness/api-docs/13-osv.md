---
source: API
url: https://google.github.io/osv.dev/api/
final_url: https://google.github.io/osv.dev/api/
language: en
fetched_at: 2026-05-04
bytes: 979
---

# API

> Information about the OSV database and API.

# API (1.0)

## Download the OpenAPI specification

Download Here

## OSV API

### Want a quick example?

Please see the quickstart.

### How does the API work?

There are five different types of requests that can be made of the API.

1. Query vulnerabilities for a particular project at a given commit hash or version.
2. Batched query vulnerabilities for given package versions and commit hashes.
3. Return a `Vulnerability` object for a given OSV ID.
4. Return a list of probable versions of a specified C/C++ project. (**Experimental**)
5. Retrieve records failing import-time quality checks, by record source (**Experimental**)

### Is the API rate limited?

Currently there are no limits on the API.

### Are there any response size limits?

The API has a response size limit of 32MiB when using HTTP/1.1. There is no limit when using HTTP/2.

We recommend using HTTP/2 for queries that may result in large responses (e.g. big OSV Linux queries).

---

## Table of contents
