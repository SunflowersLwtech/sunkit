---
source: Reader API
url: https://jina.ai/reader/
final_url: https://jina.ai/reader/
language: en
fetched_at: 2026-05-04
bytes: 28296
---

# Reader API

> Convert any URL to Markdown for better grounding LLMs.

# Reader

Convert a URL to LLM-friendly input, by simply adding `r.jina.ai` in front.

---

---

## Reader API

Convert a URL to LLM-friendly input, by simply adding `r.jina.ai` in front.

API Key & Billing

Usage

More

---

Rate Limit

Raise issue

FAQ

Status

---

Use `r.jina.ai` to read a URL and fetch its content

Use `s.jina.ai` to search the web and get SERP

Add `mcp.jina.ai` as your MCP server to access our API in LLMs

---

Parameters

The target URL to fetch content from

Add API Key for Higher Rate Limit

Enter your Jina API key to access a higher rate limit. For latest rate limit information, please refer to the table below.Learn more

Browser Engine (Quality/Speed)

Choose the browser engine for fetching the webpage content. This affects the quality, speed, completeness, accessibility of the content.Learn more

Default

Content Format

You can control the level of detail in the response to prevent over-filtering. The default pipeline is optimized for most websites and LLM input.

Default

JSON Response

The response will be in JSON format, containing the URL, title, content, and timestamp (if available). In Search mode, it returns a list of five entries, each following the described JSON structure.

Timeout (seconds)

Maximum time to wait for page load. Increase for slow pages, decrease for simple static pages.

Token Budget

Limits the maximum number of tokens used for this request. Exceeding this limit will cause the request to fail.

Use ReaderLM-v2

Experimental

Uses ReaderLM-v2 for HTML to Markdown conversion, to deliver high-quality results for websites with complex structures and contents. Costs 3x tokens!Learn more

Extract Only (CSS Selector)

Only extract content matching these CSS selectors. Example: article, .main-content, #post-body

body

.class

#id

Wait For (CSS Selector)

Wait until these elements appear before extracting content. Useful for dynamically loaded content.

body

.class

#id

Exclude (CSS Selector)

Remove these elements before extraction. Example: nav, footer, .sidebar, #ads

header

.class

#id

Remove All Images

Strip all images from the output. Reduces token usage when images are not needed.

OpenAI Citation Format

Format links for OpenAI's web browsing tool. Uses special citation markers compatible with GPT models.Learn more

Links Summary Section

A "Buttons & Links" section will be created at the end. This helps the downstream LLMs or web agents navigating the page or take further actions.

None

Images Summary Section

An "Images" section will be created at the end. This gives the downstream LLMs an overview of all visuals on the page, which may improve reasoning.

None

Browser Viewport Size

POST

Set browser window dimensions. Affects responsive layouts and content visibility.Learn more

Forward Cookie

Our API server can forward your custom cookie settings when accessing the URL, which is useful for pages requiring extra authentication. Note that requests with cookies will not be cached.Learn more

<cookie-name>=<cookie-value>

<cookie-name-1>=<cookie-value>; domain=<cookie-1-domain>

Image Caption

Captions all images at the specified URL, adding 'Image [idx]: [caption]' as an alt tag for those without one. This allows downstream LLMs to interact with the images in activities such as reasoning and summarizing.

Use a Proxy Server

Our API server can utilize your proxy to access URLs, which is helpful for pages accessible only through specific proxies.Learn more

Use a Country-Specific Proxy Server

Set country code for location-based proxy server. Use 'auto' for optimal selection or 'none' to disable.

Bypass Cached Content

Our API caches URL contents for a certain amount of time. Set it to true to ignore the cached result and fetch the content from the URL directly.

Cache Tolerance (seconds)

Accept cached content if younger than N seconds. Set to 0 for fresh content (same as Bypass Cache), or higher values to allow faster responses from cache.

Page Ready Timing

When to consider a page fully loaded. Later timings wait longer but capture more dynamic content.

Default

Custom User-Agent

Override the browser User-Agent string. Useful for accessing sites that require specific browsers or block crawlers.

Custom Referer

Set the HTTP Referer header. Some sites check this to verify traffic comes from expected sources.

Preserve Base64 Images

Keep inline base64-encoded images in markdown output instead of converting them to external URLs.

Do Not Cache or Track

Prevent this request from being cached or logged on our servers. Use for sensitive URLs.

Github Flavored Markdown

Opt in/out features from GFM (Github Flavored Markdown).

Enabled

Stream Mode

Stream mode is beneficial for large target pages, allowing more time for the page to fully render. If standard mode results in incomplete content, consider using Stream mode.Learn more

Customize Browser Locale

Control the browser locale to render the page. Lots of websites serve different content based on the locale.Learn more

Respect robots.txt

Check robots.txt rules before fetching. Specify which bot name to use for the check.

Include iframe Content

Extract content from embedded iframes. Enable for pages with content loaded in iframes.

Include Shadow DOM

Extract content from Shadow DOM components. Enable for pages using web components.

Use Final URL as Base

Resolve relative URLs using the final destination URL after redirects, instead of the original URL.

Local PDF/HTML file

POST

Use Reader on your local PDF and HTML file by uploading them. Only support pdf and html files. For HTML, please also specify a reference URL for better parsing related CSS/JS scripts.

Run JavaScript Before Extraction

POST

Execute custom JS to modify the page before content extraction. Can be inline code or a URL to a script file.Learn more

Heading Style

Sets markdown heading format (passed to Turndown).

Hash Style

Horizontal Rule Style

Defines markdown horizontal rule format (passed to Turndown).

Bullet Point Style

Sets bullet list marker character (passed to Turndown).

\*

Emphasis Style

Defines markdown emphasis delimiter (passed to Turndown).

\_

Strong Emphasis Style

Sets markdown strong emphasis delimiter (passed to Turndown).

\*\*

Link Style

Determines markdown link format (passed to Turndown).

Inline

EU Compliance

Experimental

All infrastructure and data processing operations reside entirely within EU jurisdiction.

---

Request

GET

Bash

Language

```
curl "https://r.jina.ai/https://www.example.com"
```

---

---

API key

---

Available tokens

0

This is your unique key. Store it securely!

A 2.4B parameter vision-language model that achieves state-of-the-art multilingual visual question answering among open 2B-scale VLMs.

Read Release Note

ReaderLM-v2 is a 1.5B parameter language model specialized in HTML-to-Markdown conversion and HTML-to-JSON extraction. It supports documents up to 512K tokens across 29 languages and offers 20% higher accuracy compared to its predecessor.

## What is Reader?

Feeding web information into LLMs is an important step of grounding, yet it can be challenging. The simplest method is to scrape the webpage and feed the raw HTML. However, scraping can be complex and often blocked, and raw HTML is cluttered with extraneous elements like markups and scripts. The Reader API addresses these issues by extracting the core content from a URL and converting it into clean, LLM-friendly text, ensuring high-quality input for your agent and RAG systems.

Enter your URL

Click below to fetch the source code of the page directly

---

Reader URL

Click below to obtain the content through our Reader API

---

---

Raw HTML

---

Reader Output

---

Pose a Question

Input a question and combine it with the fetched content for LLM to generate an answer

## Reader for web search and SERP

Reader can be used as SERP API. It allows you to feed your LLM with the content behind the search results engine page. Simply prepend `https://s.jina.ai/?q=` to your query, and Reader will search the web and return the top five results with their URLs and contents, each in clean, LLM-friendly text. This way, you can always keep your LLM up-to-date, improve its factuality, and reduce hallucinations.

Enter your query

Type a question that requires latest information or world knowledge.

---

Reader URL

If you use this URL in code, dont forget to encode the URL.

---

---

Please note that unlike the demo shown above, in practice you do not search the original question on the web for grounding. What people often do is rewrite the original question or use multi-hop questions. They read the retrieved results and then generate additional queries to gather more information as needed before arriving at a final answer.

## Reader also reads images!

Images on the webpage are automatically captioned using a vision language model in the reader and formatted as image alt tags in the output. This gives your downstream LLM just enough hints to incorporate those images into its reasoning and summarizing processes. This means you can ask questions about the images, select specific ones, or even forward their URLs to a more powerful VLM for deeper analysis!

## Reader also reads PDFs!

Yes, Reader natively supports PDF reading. It's compatible with most PDFs, including those with many images, and it's lightning fast! Combined with an LLM, you can easily build a ChatPDF or document analysis AI in no time.

Original PDF

---

Reader Result

## The best part? It's free!

Reader API is available for free and offers flexible rate limit and pricing. Built on a scalable infrastructure, it offers high accessibility, concurrency, and reliability. We strive to be your preferred grounding solution for your LLMs.

Rate Limit

Rate limits are tracked in three ways: **RPM** (requests per minute), and **TPM** (tokens per minute). Limits are enforced per IP/API key and will be triggered when either the RPM or TPM threshold is reached first. When you provide an API key in the request header, we track rate limits by key rather than IP address.

Columns

|  | Product | API Endpoint | Description | w/o API Key | w/ Free API Key | w/ Paid API Key | w/ Premium API Key | Average Latency | Token Usage Counting | Allowed Request |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  | Reader API | `https://r.jina.ai` | Convert URL to LLM-friendly text | 20 RPM | 500 RPM | 500 RPM | 5000 RPM | 7.9s | Count the number of tokens in the output response. | GET/POST |
|  | Reader API | `https://s.jina.ai` | Search the web and convert results to LLM-friendly text |  | 100 RPM | 100 RPM | 1000 RPM | 2.5s | Every request costs a fixed number of tokens, starting from 10000 tokens | GET/POST |
|  | Embedding API | `https://api.jina.ai/v1/embeddings` | Convert text/images to fixed-length vectors |  | 100 RPM & 100,000 TPM | 500 RPM & 2,000,000 TPM | 5,000 RPM & 50,000,000 TPM | depends on the input size | Count the number of tokens in the input request. | POST |
|  | Reranker API | `https://api.jina.ai/v1/rerank` | Rank documents by query |  | 100 RPM & 100,000 TPM | 500 RPM & 2,000,000 TPM | 5,000 RPM & 50,000,000 TPM | depends on the input size | Count the number of tokens in the input request. | POST |
|  | Classifier API | `https://api.jina.ai/v1/train` | Train a classifier using labeled examples |  | 25 RPM & 25,000 TPM | 125 RPM & 500,000 TPM | 1,250 RPM & 12,000,000 TPM | depends on the input size | Tokens counted as: input\_tokens × num\_iters | POST |
|  | Classifier API (Few-shot) | `https://api.jina.ai/v1/classify` | Classify inputs using a trained few-shot classifier |  | 25 RPM & 25,000 TPM | 125 RPM & 500,000 TPM | 1,250 RPM & 12,000,000 TPM | depends on the input size | Tokens counted as: input\_tokens | POST |
|  | Classifier API (Zero-shot) | `https://api.jina.ai/v1/classify` | Classify inputs using zero-shot classification |  | 25 RPM & 25,000 TPM | 125 RPM & 500,000 TPM | 1,250 RPM & 12,000,000 TPM | depends on the input size | Tokens counted as: input\_tokens + label\_tokens | POST |
|  | Segmenter API | `https://api.jina.ai/v1/segment` | Tokenize and segment long text | 20 RPM | 200 RPM | 200 RPM | 1,000 RPM | 0.3s | Token is not counted as usage. | GET/POST |
|  | DeepSearch | `https://deepsearch.jina.ai/v1/chat/completions` | Reason, search and iterate to find the best answer |  | 50 RPM | 50 RPM | 500 RPM | 56.7s | Count the total number of tokens in the whole process. | POST |

Don't panic! Every new API key contains ten millions free tokens!

---

## API Pricing

API pricing is based on the token usage. One API key gives you access to all search foundation products.

With Jina Search Foundation API

The easiest way to access all of our products. Top-up tokens as you go.

Enter the API key you wish to recharge

Top up this API key with more tokens

Depending on your location, you may be charged in USD, EUR, or other currencies. Taxes may apply.

Please input the right API key to top up

Understand the rate limit

Rate limits are the maximum number of requests that can be made to an API within a minute per IP address/API key (RPM). Find out more about the rate limits for each product and tier below.

Rate Limit

Rate limits are tracked in three ways: **RPM** (requests per minute), and **TPM** (tokens per minute). Limits are enforced per IP/API key and will be triggered when either the RPM or TPM threshold is reached first. When you provide an API key in the request header, we track rate limits by key rather than IP address.

Columns

|  | Product | API Endpoint | Description | w/o API Key | w/ Free API Key | w/ Paid API Key | w/ Premium API Key | Average Latency | Token Usage Counting | Allowed Request |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  | Reader API | `https://r.jina.ai` | Convert URL to LLM-friendly text | 20 RPM | 500 RPM | 500 RPM | 5000 RPM | 7.9s | Count the number of tokens in the output response. | GET/POST |
|  | Reader API | `https://s.jina.ai` | Search the web and convert results to LLM-friendly text |  | 100 RPM | 100 RPM | 1000 RPM | 2.5s | Every request costs a fixed number of tokens, starting from 10000 tokens | GET/POST |
|  | Embedding API | `https://api.jina.ai/v1/embeddings` | Convert text/images to fixed-length vectors |  | 100 RPM & 100,000 TPM | 500 RPM & 2,000,000 TPM | 5,000 RPM & 50,000,000 TPM | depends on the input size | Count the number of tokens in the input request. | POST |
|  | Reranker API | `https://api.jina.ai/v1/rerank` | Rank documents by query |  | 100 RPM & 100,000 TPM | 500 RPM & 2,000,000 TPM | 5,000 RPM & 50,000,000 TPM | depends on the input size | Count the number of tokens in the input request. | POST |
|  | Classifier API | `https://api.jina.ai/v1/train` | Train a classifier using labeled examples |  | 25 RPM & 25,000 TPM | 125 RPM & 500,000 TPM | 1,250 RPM & 12,000,000 TPM | depends on the input size | Tokens counted as: input\_tokens × num\_iters | POST |
|  | Classifier API (Few-shot) | `https://api.jina.ai/v1/classify` | Classify inputs using a trained few-shot classifier |  | 25 RPM & 25,000 TPM | 125 RPM & 500,000 TPM | 1,250 RPM & 12,000,000 TPM | depends on the input size | Tokens counted as: input\_tokens | POST |
|  | Classifier API (Zero-shot) | `https://api.jina.ai/v1/classify` | Classify inputs using zero-shot classification |  | 25 RPM & 25,000 TPM | 125 RPM & 500,000 TPM | 1,250 RPM & 12,000,000 TPM | depends on the input size | Tokens counted as: input\_tokens + label\_tokens | POST |
|  | Segmenter API | `https://api.jina.ai/v1/segment` | Tokenize and segment long text | 20 RPM | 200 RPM | 200 RPM | 1,000 RPM | 0.3s | Token is not counted as usage. | GET/POST |
|  | DeepSearch | `https://deepsearch.jina.ai/v1/chat/completions` | Reason, search and iterate to find the best answer |  | 50 RPM | 50 RPM | 500 RPM | 56.7s | Count the total number of tokens in the whole process. | POST |

Auto top-up on low token balance

Recommended for uninterrupted service in production. When your token balance drops below the set threshold, we will automatically recharge your saved payment method for the last purchased package, until the threshold is met.

We introduced a new pricing model on May 6th, 2025. If you enabled auto-recharge before this date, you'll continue to pay the old price (the one when you purchased). The new pricing only applies if you modify your auto-recharge settings or purchase a new API key.

< 1M Tokens

Top up when

## FAQ

What are the costs associated with using the Reader API?

Reader API is free for basic usage - simply prepend 'https://r.jina.ai/' to your URL. For higher rate limits, you can provide an API key which charges tokens based on content length. Check Q16 for rate limit details.

How does the Reader API function?

The Reader API uses a proxy to fetch any URL, rendering its content in a browser to extract high-quality main content.

Is the Reader API open source?

Yes, the Reader API is open source and available on the Jina AI GitHub repository.

What is the typical latency for the Reader API?

The Reader API generally processes URLs and returns content within 2 seconds, although complex or dynamic pages might require more time.

Why should I use the Reader API instead of scraping the page myself?

Scraping can be complicated and unreliable, particularly with complex or dynamic pages. The Reader API provides a streamlined, reliable output of clean, LLM-ready text.

Does the Reader API support multiple languages?

The Reader API returns content in the original language of the URL. It does not provide translation services.

What should I do if a website blocks the Reader API?

If you experience blocking issues, please contact our support team for assistance and resolution.

Can the Reader API extract content from PDF files?

Yes, the Reader API can natively extract content from PDF files.

Can the Reader API process media content from web pages?

Yes, Reader can caption images on webpages using the `x-with-generated-alt` header. This adds descriptive alt tags to images that lack them, enabling LLMs to understand visual content. Video summarization is planned for future releases.

Is it possible to use the Reader API on local HTML files?

No, the Reader API can only process content from publicly accessible URLs.

Does Reader API cache the content?

If you request the same URL within 5 minutes, the Reader API will return the cached content.

Can I use the Reader API to access content behind a login?

Unfortunately not.

Can I use the Reader API to access PDF on arXiv?

Yes, you can either use the native PDF support from the Reader (https://r.jina.ai/https://arxiv.org/pdf/2310.19923v4) or use the HTML version from the arXiv (https://r.jina.ai/https://arxiv.org/html/2310.19923v4)

How does image caption work in Reader?

Reader captions all images at the specified URL and adds `Image [idx]: [caption]` as an alt tag (if they initially lack one). This enables downstream LLMs to interact with the images in reasoning, summarizing etc.

What is the scalability of the Reader? Can I use it in production?

The Reader API is designed to be highly scalable. It is auto-scaled based on the real-time traffic and the maximum concurrency requests is now around 4000. We are maintaining it actively as one of the core products of Jina AI. So feel free to use it in production.

What is the rate limit of the Reader API?

Please find the latest rate limit information in the table below. Note that we are actively working on improving the rate limit and performance of the Reader API, the table will be updated accordingly.

Rate limit

What is Reader-LM? How can I use it?

`ReaderLM-v2` is our latest small language model (SLM) for converting raw HTML into clean markdown or JSON. It offers a 3x quality improvement over v1 and can extract structured data using JSON schema or natural language instructions. You can use it directly via Reader API with the `x-respond-with: readerlm-v2` header, or deploy it from cloud marketplaces (AWS, Azure, GCP).

AWS SageMakerGoogle CloudMicrosoft Azure

How do I extract structured data from webpages?

Use the `x-json-schema` header with a JSON schema definition, or use `x-instruction` header with natural language instructions. Both features work with ReaderLM-v2 to extract specific fields like prices, titles, dates, etc. from any webpage into structured JSON format.

Does Reader actively bypass website anti-bot protection?

No. Reader does not actively circumvent or bypass any website defense mechanisms, anti-bot systems, or access controls. If a website detects our service as a bot and blocks the request, that outcome is respected. We operate as a standard web client and do not employ techniques designed to evade detection systems.

Will upgrading from a free to a paid API key give me access to more websites?

No. Upgrading from a free tier to a paid API key does not grant access to additional websites or bypass any site restrictions. The difference between tiers is primarily in rate limits and performance optimizations. A paid API key provides higher request throughput and faster processing, but it does not enable access to websites that block our service.

### How to get my API key?

### What's the rate limit?

Rate Limit

Rate limits are tracked in three ways: **RPM** (requests per minute), and **TPM** (tokens per minute). Limits are enforced per IP/API key and will be triggered when either the RPM or TPM threshold is reached first. When you provide an API key in the request header, we track rate limits by key rather than IP address.

Columns

|  | Product | API Endpoint | Description | w/o API Key | w/ Free API Key | w/ Paid API Key | w/ Premium API Key | Average Latency | Token Usage Counting | Allowed Request |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  | Reader API | `https://r.jina.ai` | Convert URL to LLM-friendly text | 20 RPM | 500 RPM | 500 RPM | 5000 RPM | 7.9s | Count the number of tokens in the output response. | GET/POST |
|  | Reader API | `https://s.jina.ai` | Search the web and convert results to LLM-friendly text |  | 100 RPM | 100 RPM | 1000 RPM | 2.5s | Every request costs a fixed number of tokens, starting from 10000 tokens | GET/POST |
|  | Embedding API | `https://api.jina.ai/v1/embeddings` | Convert text/images to fixed-length vectors |  | 100 RPM & 100,000 TPM | 500 RPM & 2,000,000 TPM | 5,000 RPM & 50,000,000 TPM | depends on the input size | Count the number of tokens in the input request. | POST |
|  | Reranker API | `https://api.jina.ai/v1/rerank` | Rank documents by query |  | 100 RPM & 100,000 TPM | 500 RPM & 2,000,000 TPM | 5,000 RPM & 50,000,000 TPM | depends on the input size | Count the number of tokens in the input request. | POST |
|  | Classifier API | `https://api.jina.ai/v1/train` | Train a classifier using labeled examples |  | 25 RPM & 25,000 TPM | 125 RPM & 500,000 TPM | 1,250 RPM & 12,000,000 TPM | depends on the input size | Tokens counted as: input\_tokens × num\_iters | POST |
|  | Classifier API (Few-shot) | `https://api.jina.ai/v1/classify` | Classify inputs using a trained few-shot classifier |  | 25 RPM & 25,000 TPM | 125 RPM & 500,000 TPM | 1,250 RPM & 12,000,000 TPM | depends on the input size | Tokens counted as: input\_tokens | POST |
|  | Classifier API (Zero-shot) | `https://api.jina.ai/v1/classify` | Classify inputs using zero-shot classification |  | 25 RPM & 25,000 TPM | 125 RPM & 500,000 TPM | 1,250 RPM & 12,000,000 TPM | depends on the input size | Tokens counted as: input\_tokens + label\_tokens | POST |
|  | Segmenter API | `https://api.jina.ai/v1/segment` | Tokenize and segment long text | 20 RPM | 200 RPM | 200 RPM | 1,000 RPM | 0.3s | Token is not counted as usage. | GET/POST |
|  | DeepSearch | `https://deepsearch.jina.ai/v1/chat/completions` | Reason, search and iterate to find the best answer |  | 50 RPM | 50 RPM | 500 RPM | 56.7s | Count the total number of tokens in the whole process. | POST |

API-related common questions

Can I use the same API key for reader, embedding, reranking, classifying and fine-tuning APIs?

Yes, the same API key is valid for all search foundation products from Jina AI. This includes the reader, embedding, reranking, classifying and fine-tuning APIs, with tokens shared between the all services.

Can I monitor the token usage of my API key?

Yes, token usage can be monitored in the 'API Key & Billing' tab by entering your API key, allowing you to view the recent usage history and remaining tokens. If you have logged in to the API dashboard, these details can also be viewed in the 'Manage API Key' tab.

What should I do if I forget my API key?

If you have misplaced a topped-up key and wish to retrieve it, please contact support AT jina.ai with your registered email for assistance. It's recommended to log in to keep your API key securely stored and easily accessible.

Contact

Do API keys expire?

No, our API keys do not have an expiration date. However, if you suspect your key has been compromised and wish to retire it, please contact our support team for assistance. You can also revoke your key in the API Key Management dashboard.

Contact

Can I transfer tokens between API keys?

Yes, you can transfer tokens from a premium key to another. After logging into your account on the API Key Management dashboard, use the settings of the key you want to transfer out to move all remaining paid tokens.

Can I revoke my API key?

Yes, you can revoke your API key if you believe it has been compromised. Revoking a key will immediately disable it for all users who have stored it, and all remaining balance and associated properties will be permanently unusable. If the key is a premium key, you have the option to transfer the remaining paid balance to another key before revocation. Notice that this action cannot be undone. To revoke a key, go to the key settings in the API Key Management dashboard.

Why is the first request for some models slow?

This is because our serverless architecture offloads certain models during periods of low usage. The initial request activates or 'warms up' the model, which may take a few seconds. After this initial activation, subsequent requests process much more quickly.

Is my API data used to train your models?

No. We never use your API requests, inputs, or outputs to train our embedding, reranker, or any other models. Your data remains yours.

What are the rate limits for Jina APIs?

Rate limits apply per API key:  
  
**Free:** 100 RPM, 100K TPM, 2 concurrent requests  
**Paid:** 500 RPM, 2M TPM, 50 concurrent requests  
**Premium:** 5,000 RPM, 50M TPM, 500 concurrent requests  
  
There is also an IP-based rate limit of 10,000 requests per 60 seconds. These limits apply across all Jina APIs (Embeddings, Reranker, Reader, etc.).

Are there batch size limits for the APIs?

There is **no batch size limit** for either the Embeddings or Reranker APIs. You can send as many items or documents as needed per request. Both APIs batch inputs internally by token count for optimal GPU utilization.

Billing-related common questions

Is billing based on the number of sentences or requests?

Our pricing model is based on the total number of tokens processed, allowing users the flexibility to allocate these tokens across any number of sentences, offering a cost-effective solution for diverse text analysis requirements.

Is there a free trial available for new users?

We offer a welcoming free trial to new users, which includes ten millions tokens for use with any of our models, facilitated by an auto-generated API key. Once the free token limit is reached, users can easily purchase additional tokens for their API keys via the 'Buy tokens' tab.

Are tokens charged for failed requests?

No, tokens are not deducted for failed requests.

What payment methods are accepted?

Payments are processed through Stripe, supporting a variety of payment methods including credit cards, Google Pay, and PayPal for your convenience.

Is invoicing available for token purchases?

Yes, an invoice will be issued to the email address associated with your Stripe account upon the purchase of tokens.
