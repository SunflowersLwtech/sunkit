---
source: Scrape - Firecrawl Docs
url: https://docs.firecrawl.dev/api-reference/endpoint/scrape
final_url: https://docs.firecrawl.dev/api-reference/endpoint/scrape
language: en
fetched_at: 2026-05-04
bytes: 11615
---

# Scrape - Firecrawl Docs

> 

POST

/

scrape

Scrape a single URL and optionally extract information using an LLM

```
curl --request POST \
  --url https://api.firecrawl.dev/v2/scrape \
  --header 'Authorization: Bearer <token>' \
  --header 'Content-Type: application/json' \
  --data '
{
  "url": "<string>",
  "formats": [
    "markdown"
  ],
  "onlyMainContent": true,
  "onlyCleanContent": false,
  "includeTags": [
    "<string>"
  ],
  "excludeTags": [
    "<string>"
  ],
  "maxAge": 172800000,
  "minAge": 123,
  "headers": {},
  "waitFor": 0,
  "mobile": false,
  "skipTlsVerification": true,
  "timeout": 60000,
  "parsers": [
    "pdf"
  ],
  "actions": [
    {
      "type": "wait",
      "milliseconds": 2
    }
  ],
  "location": {
    "country": "US",
    "languages": [
      "en-US"
    ]
  },
  "removeBase64Images": true,
  "blockAds": true,
  "proxy": "auto",
  "storeInCache": true,
  "lockdown": false,
  "zeroDataRetention": false
}
'
```

```
{
  "success": true,
  "data": {
    "markdown": "<string>",
    "summary": "<string>",
    "html": "<string>",
    "rawHtml": "<string>",
    "screenshot": "<string>",
    "audio": "<string>",
    "links": [
      "<string>"
    ],
    "actions": {
      "screenshots": [
        "<string>"
      ],
      "scrapes": [
        {
          "url": "<string>",
          "html": "<string>"
        }
      ],
      "javascriptReturns": [
        {
          "type": "<string>",
          "value": "<unknown>"
        }
      ],
      "pdfs": [
        "<string>"
      ]
    },
    "metadata": {
      "title": "<string>",
      "description": "<string>",
      "language": "<string>",
      "sourceURL": "<string>",
      "url": "<string>",
      "keywords": "<string>",
      "ogLocaleAlternate": [
        "<string>"
      ],
      "<any other metadata> ": "<string>",
      "statusCode": 123,
      "contentType": "<string>",
      "error": "<string>",
      "concurrencyLimited": true,
      "concurrencyQueueDurationMs": 123
    },
    "warning": "<string>",
    "changeTracking": {
      "previousScrapeAt": "2023-11-07T05:31:56Z",
      "changeStatus": "new",
      "visibility": "visible",
      "diff": "<string>",
      "json": {}
    },
    "branding": {
      "colorScheme": "light",
      "logo": "<string>",
      "colors": {
        "primary": "<string>",
        "secondary": "<string>",
        "accent": "<string>",
        "background": "<string>",
        "textPrimary": "<string>",
        "textSecondary": "<string>",
        "link": "<string>",
        "success": "<string>",
        "warning": "<string>",
        "error": "<string>"
      },
      "fonts": [
        {
          "family": "<string>"
        }
      ],
      "typography": {
        "fontFamilies": {
          "primary": "<string>",
          "heading": "<string>",
          "code": "<string>"
        },
        "fontSizes": {
          "h1": "<string>",
          "h2": "<string>",
          "h3": "<string>",
          "body": "<string>"
        },
        "fontWeights": {
          "light": 123,
          "regular": 123,
          "medium": 123,
          "bold": 123
        },
        "lineHeights": {
          "heading": "<string>",
          "body": "<string>"
        }
      },
      "spacing": {
        "baseUnit": 123,
        "borderRadius": "<string>",
        "padding": {},
        "margins": {}
      },
      "components": {
        "buttonPrimary": {
          "background": "<string>",
          "textColor": "<string>",
          "borderRadius": "<string>"
        },
        "buttonSecondary": {
          "background": "<string>",
          "textColor": "<string>",
          "borderColor": "<string>",
          "borderRadius": "<string>"
        },
        "input": {}
      },
      "icons": {},
      "images": {
        "logo": "<string>",
        "favicon": "<string>",
        "ogImage": "<string>"
      },
      "animations": {},
      "layout": {},
      "personality": {}
    }
  }
}
```

> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.firecrawl.dev/llms.txt
>
> Use this file to discover all available pages before exploring further.

##  Interactions

For browser interactions (clicking, typing, navigating, extracting dynamic content), use the Interact endpoint. Scrape a page first, then call `POST /v2/scrape/{scrapeId}/interact` with a natural-language prompt or Playwright code to take actions on the page.
See the Interact documentation for full details and examples.
Optionally you can also use the `actions` parameter, although it’s not recommended to use it for complex interactions.
> Are you an AI agent that needs a Firecrawl API key? See firecrawl.dev/agent-onboarding/SKILL.md for automated onboarding instructions.

#### Authorizations



Authorization

string

header

required

Bearer authentication header of the form `Bearer <token>`, where `<token>` is your auth token.

#### Body

application/json



url

string<uri>

required

The URL to scrape



formats

(Markdown · object | Summary · object | HTML · object | Raw HTML · object | Links · object | Images · object | Screenshot · object | JSON · object | Change Tracking · object | Branding · object | Audio · object)[]

Output formats to include in the response. You can specify one or more formats, either as strings (e.g., `'markdown'`) or as objects with additional options (e.g., `{ type: 'json', schema: {...} }`). Some formats require specific options to be set. Example: `['markdown', { type: 'json', schema: {...} }]`.

* Markdown
* Summary
* HTML
* Raw HTML
* Links
* Images
* Screenshot
* JSON
* Change Tracking
* Branding
* Audio

Show child attributes



onlyMainContent

boolean

default:true

Only return the main content of the page excluding headers, navs, footers, etc. This is a deterministic HTML-level filter applied before markdown is generated; no LLM is involved.



onlyCleanContent

boolean

default:false

Beta. Run an additional LLM-based pass over the generated markdown to remove residual boilerplate that `onlyMainContent` can miss (cookie banners, ad blocks, social share widgets, breadcrumbs, newsletter signups, comment sections, related-article lists). Headings, lists, tables, code blocks, image references, and inline links are preserved. Can be combined with `onlyMainContent` (the most common setup) or used on its own. Skipped with a warning when the markdown exceeds the cleaning model's output token limit (the original markdown is preserved). Not supported on zero-data-retention requests.



includeTags

string[]

Tags to include in the output.



excludeTags

string[]

Tags to exclude from the output.



maxAge

integer

default:172800000

Returns a cached version of the page if it is younger than this age in milliseconds. If a cached version of the page is older than this value, the page will be scraped. If you do not need extremely fresh data, enabling this can speed up your scrapes by 500%. Defaults to 2 days.



minAge

integer

When set, the request only checks the cache and never triggers a fresh scrape. The value is in milliseconds and specifies the minimum age the cached data must be. If matching cached data exists, it is returned instantly. If no cached data is found, a 404 with error code SCRAPE\_NO\_CACHED\_DATA is returned. Set to 1 to accept any cached data regardless of age.



headers

object

Headers to send with the request. Can be used to send cookies, user-agent, etc.



waitFor

integer

default:0

Specify a delay in milliseconds before fetching the content, allowing the page sufficient time to load. This waiting time is in addition to Firecrawl's smart wait feature.



mobile

boolean

default:false

Set to true if you want to emulate scraping from a mobile device. Useful for testing responsive pages and taking mobile screenshots.



skipTlsVerification

boolean

default:true

Skip TLS certificate verification when making requests.



timeout

integer

default:60000

Timeout in milliseconds for the request. Minimum is 1000 (1 second). Default is 60000 (60 seconds). Maximum is 300000 (300 seconds).

Required range: `1000 <= x <= 300000`



parsers

object[]

Controls how files are processed during scraping. When "pdf" is included (default), the PDF content is extracted and converted to markdown format, with billing based on the number of pages (1 credit per page). When an empty array is passed, the PDF file is returned in base64 encoding with a flat rate of 1 credit for the entire PDF.

Show child attributes



actions

(Wait by Duration · object | Wait for Element · object | Screenshot · object | Click · object | Write text · object | Press a key · object | Scroll · object | Scrape · object | Execute JavaScript · object | Generate PDF · object)[]

Actions to perform on the page before grabbing the content

* Wait by Duration
* Wait for Element
* Screenshot
* Click
* Write text
* Press a key
* Scroll
* Scrape
* Execute JavaScript
* Generate PDF

Show child attributes



location

object

Location settings for the request. When specified, this will use an appropriate proxy if available and emulate the corresponding language and timezone settings. Defaults to 'US' if not specified.

Show child attributes



removeBase64Images

boolean

default:true

Removes all base 64 images from the markdown output, which may be overwhelmingly long. This does not affect html or rawHtml formats. The image's alt text remains in the output, but the URL is replaced with a placeholder.



blockAds

boolean

default:true

Enables ad-blocking and cookie popup blocking.



proxy

enum<string>

default:auto

Specifies the type of proxy to use.

* basic: Proxies for scraping sites with none to basic anti-bot solutions. Fast and usually works.
* enhanced: Enhanced proxies for scraping sites with advanced anti-bot solutions. Slower, but more reliable on certain sites. Costs up to 5 credits per request.
* auto: Firecrawl will automatically retry scraping with enhanced proxies if the basic proxy fails. If the retry with enhanced is successful, 5 credits will be billed for the scrape. If the first attempt with basic is successful, only the regular cost will be billed.

Available options:

`basic`,

`enhanced`,

`auto`



storeInCache

boolean

default:true

If true, the page will be stored in the Firecrawl index and cache. Setting this to false is useful if your scraping activity may have data protection concerns. Using some parameters associated with sensitive scraping (e.g. actions, headers) will force this parameter to be false.



lockdown

boolean

default:false

If true, serves the request from Firecrawl's cache only and never makes an outbound request to the target URL. Designed for compliance-constrained or air-gapped environments where the scrape request itself could leak sensitive information. On cache miss, returns a 404 with error code SCRAPE\_LOCKDOWN\_CACHE\_MISS (the URL is never logged on miss). Lockdown requests are treated as zero data retention. Default maxAge is extended to 2 years so existing cached pages remain eligible. Billed at 5 credits on hit, 1 credit on cache miss.



profile

object

Enable persistent browser storage across scrape and interact sessions. Pass a profile when scraping to preserve cookies, localStorage, and session data. Sessions with the same profile name share browser state.

Show child attributes



zeroDataRetention

boolean

default:false

If true, this will enable zero data retention for this scrape. To enable this feature, please contact help@firecrawl.dev

#### Response

Successful response



success

boolean



data

object

Show child attributes
