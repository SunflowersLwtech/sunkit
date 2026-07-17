---
source: Search - Exa
url: https://docs.exa.ai/reference/search
final_url: https://exa.ai/docs/reference/search
language: en
fetched_at: 2026-05-04
bytes: 9871
---

# Search - Exa

> The search endpoint lets you search the web and extract contents from the results.

POST

/

search

```
curl -X POST 'https://api.exa.ai/search' \
  -H 'x-api-key: YOUR-EXA-API-KEY' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "Latest research in LLMs",
    "contents": {
      "highlights": true
    }
  }'
```

```
{
  "requestId": "b5947044c4b78efa9552a7c89b306d95",
  "results": [
    {
      "title": "A Comprehensive Overview of Large Language Models",
      "url": "https://arxiv.org/pdf/2307.06435.pdf",
      "publishedDate": "2023-11-16T01:36:32.547Z",
      "author": "Humza  Naveed, University of Engineering and Technology (UET), Lahore, Pakistan",
      "id": "https://arxiv.org/abs/2307.06435",
      "image": "https://arxiv.org/pdf/2307.06435.pdf/page_1.png",
      "favicon": "https://arxiv.org/favicon.ico",
      "text": "Abstract Large Language Models (LLMs) have recently demonstrated remarkable capabilities...",
      "highlights": [
        "Such requirements have limited their adoption..."
      ],
      "highlightScores": [
        0.4600165784358978
      ],
      "summary": "This overview paper on Large Language Models (LLMs) highlights key developments...",
      "subpages": [
        {
          "id": "https://arxiv.org/abs/2303.17580",
          "url": "https://arxiv.org/pdf/2303.17580.pdf",
          "title": "HuggingGPT: Solving AI Tasks with ChatGPT and its Friends in Hugging Face",
          "author": "Yongliang  Shen, Microsoft Research Asia, Kaitao  Song, Microsoft Research Asia, Xu  Tan, Microsoft Research Asia, Dongsheng  Li, Microsoft Research Asia, Weiming  Lu, Microsoft Research Asia, Yueting  Zhuang, Microsoft Research Asia, yzhuang@zju.edu.cn, Zhejiang  University, Microsoft Research Asia, Microsoft  Research, Microsoft Research Asia",
          "publishedDate": "2023-11-16T01:36:20.486Z",
          "text": "HuggingGPT: Solving AI Tasks with ChatGPT and its Friends in Hugging Face Date Published: 2023-05-25 Authors: Yongliang Shen, Microsoft Research Asia Kaitao Song, Microsoft Research Asia Xu Tan, Microsoft Research Asia Dongsheng Li, Microsoft Research Asia Weiming Lu, Microsoft Research Asia Yueting Zhuang, Microsoft Research Asia, yzhuang@zju.edu.cn Zhejiang University, Microsoft Research Asia Microsoft Research, Microsoft Research Asia Abstract Solving complicated AI tasks with different domains and modalities is a key step toward artificial general intelligence. While there are abundant AI models available for different domains and modalities, they cannot handle complicated AI tasks. Considering large language models (LLMs) have exhibited exceptional ability in language understanding, generation, interaction, and reasoning, we advocate that LLMs could act as a controller to manage existing AI models to solve complicated AI tasks and language could be a generic interface to empower t",
          "summary": "HuggingGPT is a framework using ChatGPT as a central controller to orchestrate various AI models from Hugging Face to solve complex tasks. ChatGPT plans the task, selects appropriate models based on their descriptions, executes subtasks, and summarizes the results. This approach addresses limitations of LLMs by allowing them to handle multimodal data (vision, speech) and coordinate multiple models for complex tasks, paving the way for more advanced AI systems.",
          "highlights": [
            "2) Recently, some researchers started to investigate the integration of using tools or models in LLMs  ."
          ],
          "highlightScores": [
            0.32679107785224915
          ]
        }
      ],
      "extras": {
        "links": []
      }
    }
  ],
  "searchType": "auto",
  "context": "<string>",
  "output": {
    "content": "<string>",
    "grounding": [
      {
        "field": "<string>",
        "citations": [
          {
            "url": "<string>",
            "title": "<string>"
          }
        ],
        "confidence": "low"
      }
    ]
  },
  "costDollars": {
    "total": 0.007,
    "breakDown": [
      {
        "search": 0.007,
        "contents": 0,
        "breakdown": {
          "neuralSearch": 0.007,
          "deepSearch": 0.012,
          "contentText": 0,
          "contentHighlight": 0,
          "contentSummary": 0
        }
      }
    ],
    "perRequestPrices": {
      "neuralSearch_1_10_results": 0.007,
      "neuralSearch_additional_result": 0.001,
      "deepSearch": 0.012,
      "deepReasoningSearch": 0.015
    },
    "perPagePrices": {
      "contentText": 0.001,
      "contentHighlight": 0.001,
      "contentSummary": 0.001
    }
  }
}
```

> ## Documentation Index
>
> Fetch the complete documentation index at: https://exa.ai/docs/llms.txt
>
> Use this file to discover all available pages before exploring further.

## Get your Exa API key

#### Authorizations



x-api-key

string

header

required

API key can be provided either via x-api-key header or Authorization header with Bearer scheme

#### Body

application/json



query

string

default:Latest developments in LLM capabilities

required

The query string for the search.

Example:

`"Latest developments in LLM capabilities"`



additionalQueries

string[]

Additional query variations for deep-search variants. When provided, these queries are used alongside the main query for more comprehensive results.

Example:

```
[  
  "LLM advancements",  
  "large language model progress"  
]
```



stream

boolean

default:false

If true, the response is returned as a server-sent events stream of OpenAI-compatible chat completion chunks.



outputSchema

object

JSON schema for synthesized output. When provided, the response includes an output object and output.content matches this schema.

Show child attributes



systemPrompt

string

Instructions that guide synthesized output and, for deep-search variants, search planning. Use this for source preferences, novelty or duplication constraints; use outputSchema to control the shape of output.content.

Example:

`"Prefer official sources and avoid duplicate results."`



type

enum<string>

default:auto

The type of search. Neural uses an embeddings-based model, auto (default) intelligently combines neural and other search methods, fast uses streamlined versions of the search models, deep-lite is lightweight synthesized output, deep is light deep search, deep-reasoning is base deep search, and instant provides the lowest latency search optimized for real-time applications.

Available options:

`neural`,

`fast`,

`auto`,

`deep-lite`,

`deep`,

`deep-reasoning`,

`instant`

Example:

`"auto"`



category

enum<string>

A data category to focus on. The `people` and `company` categories have improved quality for finding LinkedIn profiles and company pages. Note: The `company` and `people` categories only support a limited set of filters. The following parameters are NOT supported for these categories: `startPublishedDate`, `endPublishedDate`, `startCrawlDate`, `endCrawlDate`, `excludeDomains`. For `people` category, `includeDomains` only accepts LinkedIn domains. Using unsupported parameters will result in a 400 error.

Available options:

`company`,

`research paper`,

`news`,

`personal site`,

`financial report`,

`people`

Example:

`"research paper"`



userLocation

string

The two-letter ISO country code of the user, e.g. US.

Example:

`"US"`



numResults

integer

default:10

Number of results to return. Limits vary by search type:

* With "neural": max 100 results
* With deep-search variants like "deep-lite", "deep", or "deep-reasoning": max 100 results

If you want to increase the num results beyond these limits, contact sales (hello@exa.ai)

Required range: `x <= 100`

Example:

`10`



includeDomains

string[]

List of domains to include in the search. If specified, results will only come from these domains.

Maximum array length: `1200`

Example:

```
["arxiv.org", "paperswithcode.com"]
```



excludeDomains

string[]

List of domains to exclude from search results. If specified, no results will be returned from these domains.

Maximum array length: `1200`



startCrawlDate

string<date-time>

Crawl date refers to the date that Exa discovered a link. Results will include links that were crawled after this date. Must be specified in ISO 8601 format.

Example:

`"2023-01-01T00:00:00.000Z"`



endCrawlDate

string<date-time>

Crawl date refers to the date that Exa discovered a link. Results will include links that were crawled before this date. Must be specified in ISO 8601 format.

Example:

`"2023-12-31T00:00:00.000Z"`



startPublishedDate

string<date-time>

Only links with a published date after this will be returned. Must be specified in ISO 8601 format.

Example:

`"2023-01-01T00:00:00.000Z"`



endPublishedDate

string<date-time>

Only links with a published date before this will be returned. Must be specified in ISO 8601 format.

Example:

`"2023-12-31T00:00:00.000Z"`



context

booleanobject

deprecated

Deprecated: Use highlights or text instead. Returns page contents as a combined context string.

Example:

`true`



moderation

boolean

default:false

Enable content moderation to filter unsafe content from search results.

Example:

`true`



contents

object

Show child attributes

#### Response

OK



requestId

string

Unique identifier for the request

Example:

`"b5947044c4b78efa9552a7c89b306d95"`



results

object[]

A list of search results containing title, URL, published date, and author.

Show child attributes



searchType

enum<string>

For auto searches, indicates which search type was selected.

Available options:

`neural`,

`deep`,

`deep-reasoning`

Example:

`"auto"`



context

string

Deprecated. Combined context string from search results. Use highlights or text instead.



output

object

Synthesized output. Returned when outputSchema is provided.

Show child attributes



costDollars

object

Show child attributes
