---
source: NVD CVE API 2.0
url: https://nvd.nist.gov/developers/vulnerabilities
fetcher: r.jina.ai (TinyFish proxy_error fallback)
fetched_at: 2026-05-04
bytes:    50381
---

Title: Vulnerability APIs

URL Source: https://nvd.nist.gov/developers/vulnerabilities

Markdown Content:
# Vulnerability APIs

# You are viewing this page in an unauthorized frame window.

This is a potential security issue, you are being redirected to [https://nvd.nist.gov](https://nvd.nist.gov/)

![Image 1: U.S. flag](https://nvd.nist.gov/site-media/images/usbanner/us_flag_small.png)An official website of the United States government Here's how you know

![Image 2: Dot gov](https://nvd.nist.gov/site-media/images/usbanner/icon-dot-gov.svg)

**Official websites use .gov**

 A **.gov** website belongs to an official government organization in the United States.

![Image 3: Https](https://nvd.nist.gov/site-media/images/usbanner/icon-https.svg)

**Secure .gov websites use HTTPS**

 A **lock** (![Image 4: Dot gov](https://nvd.nist.gov/site-media/images/usbanner/lock.svg)) or **https://** means you've safely connected to the .gov website. Share sensitive information only on official, secure websites.

[![Image 5: National Institute of Standards and Technology](https://nvd.nist.gov/site-media/images/nist/nist-logo.svg)](https://www.nist.gov/)

[NVD MENU](https://nvd.nist.gov/developers/vulnerabilities)

*   [General Expand or Collapse](https://nvd.nist.gov/general)[NVD Dashboard](https://nvd.nist.gov/general/nvd-dashboard)

[News and Status Updates](https://www.nist.gov/itl/nvd) [FAQ](https://nvd.nist.gov/general/faq) [Visualizations](https://nvd.nist.gov/general/visualizations)

[Legal Disclaimer](https://nvd.nist.gov/general/legal-disclaimer)   
*   [Vulnerabilities Expand or Collapse](https://nvd.nist.gov/vuln)[Search & Statistics](https://nvd.nist.gov/vuln/search)

[Weakness Types](https://nvd.nist.gov/vuln/categories) [Data Feeds](https://nvd.nist.gov/vuln/data-feeds)

[Vendor Comments](https://nvd.nist.gov/vuln/vendor-comments) [CVMAP](https://nvd.nist.gov/vuln/cvmap)   
*   [Vulnerability Metrics Expand or Collapse](https://nvd.nist.gov/vuln-metrics/cvss#)[CVSS v4.0 Calculators](https://nvd.nist.gov/vuln-metrics/cvss/v4-calculator) [CVSS v3.x Calculators](https://nvd.nist.gov/vuln-metrics/cvss/v3-calculator) [CVSS v2.0 Calculator](https://nvd.nist.gov/vuln-metrics/cvss/v2-calculator)   
*   [Products Expand or Collapse](https://nvd.nist.gov/products)[CPE Dictionary](https://nvd.nist.gov/products/cpe)

[CPE Search](https://nvd.nist.gov/products/cpe/search) [CPE Statistics](https://nvd.nist.gov/products/cpe/statistics)

[SWID](https://nvd.nist.gov/products/swid)    
*   [Developers Expand or Collapse](https://nvd.nist.gov/developers)[Start Here](https://nvd.nist.gov/developers/start-here)

[Request an API Key](https://nvd.nist.gov/developers/request-an-api-key) [Vulnerabilities](https://nvd.nist.gov/developers/vulnerabilities)

[Products](https://nvd.nist.gov/developers/products) [Data Sources](https://nvd.nist.gov/developers/data-sources)

[Terms of Use](https://nvd.nist.gov/developers/terms-of-use)   
*   [Contact NVD](https://nvd.nist.gov/contact)
*   [Other Sites Expand or Collapse](https://nvd.nist.gov/other)[Checklist (NCP) Repository](https://ncp.nist.gov/)

[Configurations (CCE)](https://ncp.nist.gov/cce)

[800-53 Controls](https://csrc.nist.gov/Projects/risk-management/sp800-53-controls/release-search) [SCAP](https://csrc.nist.gov/projects/security-content-automation-protocol)   
*   [Search Expand or Collapse](https://nvd.nist.gov/search)[Vulnerability Search](https://nvd.nist.gov/vuln/search) [CPE Search](https://nvd.nist.gov/products/cpe/search)   

## [Information Technology Laboratory](https://www.nist.gov/itl)

# [National Vulnerability Database](https://nvd.nist.gov/)

# National Vulnerability Database

# NVD

[![Image 6: National Vulnerability Database](https://nvd.nist.gov/site-media/images/F_NIST-Logo-NVD-white.svg)](https://nvd.nist.gov/developers/vulnerabilities)

1.   [Developers](https://nvd.nist.gov/developers)

## Vulnerabilities

This documentation assumes that you already understand at least one common programming language and are generally familiar with JSON RESTful services. JSON specifies the format of the data returned by the REST service. REST refers to a style of services that allow computers to communicate via HTTP over the Internet. Click here for a list of [best practices and additional information](https://nvd.nist.gov/developers/start-here) on where to start. The NVD is also documenting [popular workflows](https://nvd.nist.gov/developers/api-workflows) to assist developers working with the APIs.

### CVE API

The CVE API is used to easily retrieve information on a single CVE or a collection of CVE from the NVD. The NVD contains 347,891 CVE records. Because of this, its APIs enforce offset-based pagination to answer requests for large collections. Through a series of smaller “chunked” responses controlled by an offset `startIndex` and a page limit `resultsPerPage` users may page through all the CVE in the NVD.

The URL stem for retrieving CVE information is shown below.

Base URL

`https://services.nvd.nist.gov/rest/json/cves/2.0`

#### [Parameters](https://nvd.nist.gov/developers/vulnerabilities)

[cpeName optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{name}`

This parameter returns all CVE associated with a specific CPE. The exact value provided with `cpeName` is compared against the CPE Match Criteria within a CVE applicability statement. If the value of `cpeName` is considered to match, the CVE is included in the results.

A CPE Name is a string of characters comprised of 13 colon separated values that describe a product. In CPEv2.3 the first two values are always “cpe” and “2.3”. The 11 values that follow are referred to as the CPE components. When filtering by `cpeName` the part, vendor, product, and version components are required to contain values other than "*".

CPE Match Criteria comes in two forms: CPE Match Strings and CPE Match String Ranges. Both are abstract concepts that are then correlated to CPE URIs in the Official CPE Dictionary. Unlike a CPE Name, match strings and match string ranges do not require a value in the part, vendor, product, or version components. The CVE API returns CPE Match Criteria within the configurations object.

Request the CVE associated a specific CPE

`https://services.nvd.nist.gov/rest/json/cves/2.0?cpeName=cpe:2.3:o:microsoft:windows_10:1607:*:*:*:*:*:*:*`

Request the CVE associated a specific CPE using an incomplete name

`https://services.nvd.nist.gov/rest/json/cves/2.0?cpeName=cpe:2.3:o:microsoft:windows_10:1607`
[cveId optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{CVE-ID}`

This parameter returns a specific vulnerability identified by its unique Common Vulnerabilities and Exposures identifier (the CVE ID). `cveId` will not accept `{CVE-ID}` for vulnerabilities not yet published in the NVD.

Request a specific CVE using its CVE-ID

`https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2019-1010218`
[cveTag optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `disputed`
*   `unsupported-when-assigned`
*   `exclusively-hosted-service`

This parameter returns only the CVE records that include the provided `cveTag`.

Request all CVE records that have the disputed CVE Tag

`https://services.nvd.nist.gov/rest/json/cves/2.0?cveTag=disputed`
[cvssV2Metrics optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{CVSSv2 vector string}`

This parameter returns only the CVEs that match the provided `{CVSSv2 vector string}`. Either full or partial vector strings may be used. This parameter cannot be used in requests that include `cvssV3Metrics` or `cvssv4Metrics`.

Please note, as of July 2022, the NVD no longer generates new information for CVSS v2. Existing CVSS v2 information will remain in the database but the NVD will no longer actively populate CVSS v2 for new CVEs. NVD analysts will continue to use the reference information provided with the CVE and any publicly available information at the time of analysis to associate Reference Tags, information related to CVSS v3.1, CWE, and CPE Applicability statements.

Request all CVE matching the CVSSv2 vector string

`https://services.nvd.nist.gov/rest/json/cves/2.0?cvssV2Metrics=AV:N/AC:H/Au:N/C:C/I:C/A:C`

An example of a valid request for which there exists no vulnerabilities

`https://services.nvd.nist.gov/rest/json/cves/2.0?cvssV2Metrics=AV:L/AC:H/Au:M/C:N/I:N/A:N`
[cvssV2Severity optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `LOW`
*   `MEDIUM`
*   `HIGH`

This parameter returns only the CVEs that match the provided CVSSv2 qualitative severity rating. This parameter cannot be used in requests that include `cvssV3Severity` or `cvssv4Severity`.

Please note, as of July 2022, the NVD no longer generates new information for CVSS v2. Existing CVSS v2 information will remain in the database but the NVD will no longer actively populate CVSS v2 for new CVEs. NVD analysts will continue to use the reference information provided with the CVE and any publicly available information at the time of analysis to associate Reference Tags, information related to CVSS v3.1, CWE, and CPE Applicability statements.

Request all CVE matching the CVSSv2 qualitative severity rating of LOW 

`https://services.nvd.nist.gov/rest/json/cves/2.0?cvssV2Severity=LOW`
[cvssV3Metrics optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{CVSSv3 vector string}`

This parameter returns only the CVEs that match the provided `{CVSSv3 vector string}`. Either full or partial vector strings may be used. This parameter cannot be used in requests that include `cvssV2Metrics` or `cvssv4Metrics`.

Request all CVE matching the CVSSv3 vector string 

`https://services.nvd.nist.gov/rest/json/cves/2.0?cvssV3Metrics=AV:L/AC:L/PR:L/UI:R/S:U/C:N/I:L/A:L`

An example of a valid request for which there exists no vulnerabilities 

`https://services.nvd.nist.gov/rest/json/cves/2.0?cvssV3Metrics=AV:A/AC:H/PR:H/UI:R/S:C/C:H/I:H/A:H`
[cvssV3Severity optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `LOW`
*   `MEDIUM`
*   `HIGH`
*   `CRITICAL`

This parameter returns only the CVEs that match the provided CVSSv3 qualitative severity rating. This parameter cannot be used in requests that include `cvssV2Severity` or `cvssv4Severity`. 

 Note: The NVD will not contain CVSS v3 vector strings with a severity of `NONE`. This is why that severity is not an included option.

Request all CVE matching the CVSSv3 qualitative severity rating of LOW 

`https://services.nvd.nist.gov/rest/json/cves/2.0?cvssV3Severity=LOW`
[cvssV4Metrics optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{CVSSv4 vector string}`

This parameter returns only the CVEs that match the provided `{CVSSv4 vector string}`. Either full or partial vector strings may be used. This parameter cannot be used in requests that include `cvssV2Metrics` or `cvssV3Severity`.

An example of a valid request for which there exists no vulnerabilities 

`https://services.nvd.nist.gov/rest/json/cves/2.0?cvssV4Metrics=AV:A/AC:H/PR:H/UI:N`
[cvssV4Severity optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `LOW`
*   `MEDIUM`
*   `HIGH`
*   `CRITICAL`

This parameter returns only the CVEs that match the provided CVSSv4 qualitative severity rating. This parameter cannot be used in requests that include `cvssV2Severity` or `cvssV3Severity`. 

 Note: The NVD enrichment data will not contain CVSS v4 vector strings with a severity of `NONE`. This is why that severity is not an included option.

Request all CVE matching the CVSSv4 qualitative severity rating of HIGH 

`https://services.nvd.nist.gov/rest/json/cves/2.0?cvssV4Severity=HIGH`
[cweId optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{CWE-ID}`

This parameter returns only the CVE that include a weakness identified by [Common Weakness Enumeration](https://cwe.mitre.org/data/definitions/1000.html) using the provided `{CWE-ID}`. 

 Note: The NVD also makes use of two placeholder CWE-ID values `NVD-CWE-Other` and `NVD-CWE-noinfo` which can also be used.

Request all CVE that include Improper Authentication 

`https://services.nvd.nist.gov/rest/json/cves/2.0?cweId=CWE-287`
[hasCertAlerts optional](https://nvd.nist.gov/developers/vulnerabilities)
This parameter returns the CVE that contain a Technical Alert from US-CERT. Please note, this parameter is provided without a parameter value.

Request all CVE containing a Technical Alert 

`https://services.nvd.nist.gov/rest/json/cves/2.0?hasCertAlerts`
[hasCertNotes optional](https://nvd.nist.gov/developers/vulnerabilities)
This parameter returns the CVE that contain a Vulnerability Note from CERT/CC. Please note, this parameter is provided without a parameter value.

Request all CVE containing a Vulnerability Note from CERT/CC 

`https://services.nvd.nist.gov/rest/json/cves/2.0?hasCertNotes`
[hasKev optional](https://nvd.nist.gov/developers/vulnerabilities)
This parameter returns the CVE that appear in CISA's [Known Exploited Vulnerabilities](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) (KEV) Catalog. Please note, this parameter is provided without a parameter value.

Request all CVE that appear in the KEV catalog 

`https://services.nvd.nist.gov/rest/json/cves/2.0?hasKev`
[hasOval optional](https://nvd.nist.gov/developers/vulnerabilities)
This parameter returns the CVE that contain information from MITRE's [Open Vulnerability and Assessment Language](https://oval.mitre.org/inuse/) (OVAL) before this transitioned to the Center for Internet Security (CIS). Please note, this parameter is provided without a parameter value.

Request all CVE containing an OVAL record 

`https://services.nvd.nist.gov/rest/json/cves/2.0?hasOval`
[isVulnerable optional](https://nvd.nist.gov/developers/vulnerabilities)
This parameter returns only CVE associated with a specific CPE, where the CPE is also considered vulnerable. The exact value provided with `cpeName` is compared against the CPE Match Criteria within a CVE applicability statement. If the value of `cpeName` is considered to match, and is also considered vulnerable the CVE is included in the results.

If filtering by `isVulnerable`, `cpeName` is required. Please note, `virtualMatchString` is not accepted in requests that use `isVulnerable`.

Request all CVE associated a specific CPE and are marked as vulnerable 

`https://services.nvd.nist.gov/rest/json/cves/2.0?cpeName=cpe:2.3:o:microsoft:windows_10:1607&isVulnerable`
[kevStartDate & kevEndDate optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{kevStartDate}`
*   `{kevEndDate}`

These parameters return only the CVEs that were added to the [CISA Known Exploited Vulnerabilities (KEV) catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) during the specified period. If a CVE was added to the KEV catalog outside of the specified window, it will not be included. When filtering by KEV inclusion dates, both `kevStartDate` and `kevEndDate` are required.

A CVE's kevDate reflects the date it was added to the KEV catalog.

Values must be entered in the extended ISO-8601 date/time format:

`[YYYY][“-”][MM][“-”][DD][“T”][HH][“:”][MM][“:”][SS][Z]`
The "T" separates the date from the time. The "Z" indicates optional offset-from-UTC. If a positive offset is used (e.g., +01:00 for CET), encode the "+" as "%2B". Most user agents will handle this automatically.

Request all CVE records added to the KEV catalog between the start and end datetimes

`https://services.nvd.nist.gov/rest/json/cves/2.0/?kevStartDate=2023-01-01T00:00:00.000Z&kevEndDate=2023-04-30T23:59:59.000Z`
[keywordExactMatch optional](https://nvd.nist.gov/developers/vulnerabilities)
By default, `keywordSearch` returns any CVE where a word or phrase is found in the current description.

If the value of `keywordSearch` is a phrase, i.e., contains more than one term, including `keywordExactMatch` returns only the CVEs matching the phrase exactly. Otherwise, the results will contain records having any of the terms. If filtering by `keywordExactMatch`, `keywordSearch` is required. Please note, this parameter is provided without a parameter value.

Request all CVE mentioning the exact phrase "Microsoft Outlook"

`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=Microsoft Outlook&keywordExactMatch`

Please note, the example above would not return a CVE unless the exact phrase "Microsoft Outlook" appears in the current description.
[keywordSearch optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{keyword(s)}`

This parameter returns only the CVEs where a word or phrase is found in the current description. Descriptions associated with CVE are maintained by the CVE Assignment Team through coordination with CVE Numbering Authorities (CNAs). The NVD has no control over CVE descriptions.

Please note, empty spaces in the URL should be encoded in the request as "%20". The user agent may handle this encoding automatically. Multiple `{keywords}` function like an 'AND' statement. This returns results where all keywords exist somewhere in the current description, though not necessarily together. Keyword search operates as though a wildcard is placed after each keyword provided. For example, providing "circle" will return results such as "circles" but not "encircle".

Request any CVE mentioning "Microsoft"

`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=Microsoft`

Request any CVE mentioning "Windows", "MacOs", and "Debian"

`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=Windows MacOs Linux`
[lastModStartDate & lastModEndDate optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{start date}`
*   `{end date}`

These parameters return only the CVEs that were last modified during the specified period. If a CVE has been modified more recently than the specified period, it will not be included in the response. If filtering by the last modified date, both `lastModStartDate` and `lastModEndDate` are required. The maximum allowable range when using any date range parameters is 120 consecutive days.

A CVE's lastModified changes when any of the follow actions occur:

1.   The NVD publishes the new CVE record
2.   [The NVD changes the status of a published CVE record after it has been analyzed](https://nvd.nist.gov/vuln/vulnerability-status#divNvdStatus)
3.   A source (CVE Primary CNA or another CNA) modifies a published CVE record

A CVE's lastModified does not change when any of the follow actions occur:

1.   [The NVD changes the status of a newly published CVE record to "Undergoing Analysis"](https://nvd.nist.gov/vuln/vulnerability-status#divNvdStatus)
2.   The NVD modifies a CPE record previously associated with the CVE record

Values must be entered in the extended ISO-8601 date/time format:

`[YYYY][“-”][MM][“-”][DD][“T”][HH][“:”][MM][“:”][SS][Z]`
The "T" is a literal to separate the date from the time. The Z indicates an optional offset-from-UTC. Please note, if a positive Z value is used (such as +01:00 for Central European Time) then the "+" should be encoded in the request as "%2B". The user agent may handle this encoding automatically.

Request all CVE records modified between the start and end datetimes

`https://services.nvd.nist.gov/rest/json/cves/2.0/?lastModStartDate=2021-08-04T13:00:00.000%2B01:00&lastModEndDate=2021-10-22T13:36:00.000%2B01:00`
[noRejected optional](https://nvd.nist.gov/developers/vulnerabilities)
By default, the CVE API includes CVE records with the REJECT or Rejected status. This parameter excludes CVE records with the REJECT or Rejected status from API response. Please note, this parameter is provided without a parameter value.

Request all CVE without the REJECT or Rejected status

`https://services.nvd.nist.gov/rest/json/cves/2.0?noRejected`
[pubStartDate & pubEndDate optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{start date}`
*   `{end date}`

These parameters return only the CVEs that were added to the NVD (i.e., published) during the specified period. If filtering by the published date, both `pubStartDate` and `pubEndDate` are required. The maximum allowable range when using any date range parameters is 120 consecutive days.

Values must be entered in the extended ISO-8601 date/time format:

`[YYYY][“-”][MM][“-”][DD][“T”][HH][“:”][MM][“:”][SS][Z]`
The "T" is a literal to separate the date from the time. The Z indicates an optional offset-from-UTC. Please note, if a positive Z value is used (such as +01:00 for Central European Time) then the "+" should be encoded in the request as "%2B". The user agent may handle this encoding automatically.

Request all CVE published between the start and end dates, defaulting to GMT

`https://services.nvd.nist.gov/rest/json/cves/2.0/?pubStartDate=2021-08-04T00:00:00.000&pubEndDate=2021-10-22T00:00:00.000`

Request all CVE published between the start and end datetimes

`https://services.nvd.nist.gov/rest/json/cves/2.0/?pubStartDate=2020-01-01T00:00:00.000-05:00&pubEndDate=2020-01-14T23:59:59.999-05:00`
[resultsPerPage optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{page limit}`

This parameter specifies the maximum number of CVE records to be returned in a single API response. For network considerations, the default value and maximum allowable limit is 2,000.

It is recommended that users of the CVE API use the default `resultsPerPage` value. This value has been optimized to allow the greatest number of results over the fewest number of requests.
[startIndex optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{offset}`

This parameter specifies the index of the first CVE to be returned in the response data. The index is zero-based, meaning the first CVE is at index zero.

The CVE API returns four primary objects in the response body that are used for pagination: resultsPerPage, startIndex, totalResults, and vulnerabilities. totalResults indicates the total number of CVE records that match the request parameters. If the value of totalResults is greater than the value of resultsPerPage, there are more records than could be returned by a single API response and additional requests must update the `startIndex` to get the remaining records.

The best, most efficient, practice for keeping up to date with the NVD is to use the date range parameters to request only the CVEs that have been modified since your last request.

Request 20 CVE records, beginning at index 0 and ending at index 19

`https://services.nvd.nist.gov/rest/json/cves/2.0/?resultsPerPage=20&startIndex=0`

Request the CVE records, beginning at index 20 and ending at index 39

`https://services.nvd.nist.gov/rest/json/cves/2.0/?resultsPerPage=20&startIndex=20`
[sourceIdentifier optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{sourceIdentifier}`

This parameter returns CVE where the exact value of `{sourceIdentifier}` appears as a data source in the CVE record. The CVE API returns `{sourceIdentifier}` values within the descriptions object. The [Source API](https://nvd.nist.gov/developers/data-sources) returns detailed information on the organizations that provide the data contained in the NVD dataset, including every valid `{sourceIdentifier}` value.

Request all CVE with the data source "[[email protected]](https://nvd.nist.gov/cdn-cgi/l/email-protection)"

`https://services.nvd.nist.gov/rest/json/cves/[email protected]`
[versionEnd & versionEndType optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{ending version}`

*   `including`
*   `excluding`

The `virtualMatchString` parameter may be combined with `versionEnd` and `versionEndType` to return only the CVEs associated with CPEs in specific version ranges.

If filtering by the ending version, `versionEnd`, `versionEndType`, and `virtualMatchString` are required. Requests that include `versionEnd` cannot include a version component in the `virtualMatchString`.

Request all CVE affiliated with version 2.6 of a specific CPE 

`https://services.nvd.nist.gov/rest/json/cves/2.0?virtualMatchString=cpe:2.3:o:linux:linux_kernel&versionStart=2.6&versionStartType=including&versionEnd=2.7&versionEndType=excluding`
[versionStart & versionStartType optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{starting version}`

*   `including`
*   `excluding`

The `virtualMatchString` parameter may be combined with `versionStart` and `versionStartType` to return only the CVEs associated with CPEs in specific version ranges.

If filtering by the starting version, `versionStart`, `versionStartType`, and `virtualMatchString` are required. Requests that include `versionStart` cannot include a version component in the `virtualMatchString`.

Request all CVE affiliated with versions 2.2 through 2.5.x of a specific CPE 

`https://services.nvd.nist.gov/rest/json/cves/2.0?virtualMatchString=cpe:2.3:o:linux:linux_kernel&versionStart=2.2&versionStartType=including&versionEnd=2.6&versionEndType=excluding`
[virtualMatchString optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{cpe match string}`

This parameter filters CVE more broadly than `cpeName`. The exact value of `{cpe match string}` is compared against the CPE Match Criteria present on CVE applicability statements.

CPE Match Criteria comes in two forms: CPE Match Strings and CPE Match String Ranges. Both are abstract concepts that are then correlated to CPE URIs in the Official CPE Dictionary. Unlike a CPE Name, match strings and match string ranges do not require a value in the part, vendor, product, or version components. The CVE API returns CPE Match Criteria within the configurations object.

CPE Match String Ranges are only supported for the version component and only when `virtualMatchString` is combined with `versionStart`, `versionStartType`, and/or `versionEnd`, both `versionEndType`.

`cpeName` is a simpler alternative for many use cases. When both `cpeName` and `virtualMatchString` are provided, only the `cpeName` is used.

Request all CVE where the associated CPE's language component denotes the German language version of a product.

`https://services.nvd.nist.gov/rest/json/cves/2.0?virtualMatchString=cpe:2.3:*:*:*:*:*:*:de`

#### [Response](https://nvd.nist.gov/developers/vulnerabilities)

##### CVE API JSON Schema

The API response may contain up to four JSON schema that define the structure of the response data. Each of the documents below describe a different aspect of the response but all include information on data types, regex patterns, maximum character length, and other information that can support developers and database administrators looking to create their own local repository.

*   [CVE API Schema](https://csrc.nist.gov/schema/nvd/api/2.0/cve_api_json_2.0.schema)
*   [CVSSv3.1 Schema](https://csrc.nist.gov/schema/nvd/api/2.0/external/cvss-v3.1.json)
*   [CVSSv3.0 Schema](https://csrc.nist.gov/schema/nvd/api/2.0/external/cvss-v3.0.json)
*   [CVSSv2.0 Schema](https://csrc.nist.gov/schema/nvd/api/2.0/external/cvss-v2.0.json)

##### Response Details

The CVE API returns seven primary objects in the body of the response: resultsPerPage, startIndex, totalResults, format, version, timestamp, and vulnerabilities.

The totalResults object indicates the number of CVE that match the request criteria, including all parameters. If the value of totalResults is greater than the value of resultsPerPage, then additional requests are necessary to return the remaining CVE. The parameter startIndex may be used in subsequent requests to identify the starting point for the next request. More information and the best practices for using resultsPerPage and startIndex are described above.

The format and version objects identify the format and version of the API response. timestamp identifies when the response was generated.

The vulnerabilities object contains an array of objects equal to the number of CVE returned in the response and is sorted in ascending order by the published property of the cve object. The cve object is explained in more detail below.

JSON response objects are either optional or required. Required response objects are always returned by the API and may contain fields without data. Optional response objects are only returned when they contain data. For example, the cvssMetricV3 object is optional. CVSSv3.0 was released in 2016, thus most CVE published before 2016 do not include the cvssMetricV3 object. The exception are CVE published before 2016 that were later reanalyzed or modified. These CVE may have been updated to include CVSSv3 information. If the CVE was updated in this way, the API response would include this optional information.

##### cve  required

This object always contains the CVE-ID, sourceIdentifier an identifier for the source of the CVE, published the date and time that the CVE was published to the NVD, lastModified the date and time that the CVE was last modified, and vulnStatus the CVE's [status in the NVD](https://nvd.nist.gov/vuln/vulnerability-status#divNvdStatus).

This object also contains seven **optional** fields. The evaluatorComment, evaluatorImpact, and evaluatorSolution provide additional context to help understand the vulnerability or its analysis. If the CVE is listed in CISA's Known Exploited Vulnerabilities (KEV) Catalog cisaExploitAdd, cisaActionDue, cisaRequiredAction, and cisaVulnerabilityName will be returned. The cisaActionDue object indicates the date by which all federal civilian executive branch (FCEB) agencies are required to complete the cisaRequiredAction under Binding Operational Directive (BOD) 22-01, Reducing the Significant Risk of Known Exploited Vulnerabilities. Although not bound by BOD 22-01, every organization, including those in state, local, tribal, and territorial (SLTT) governments and private industry can significantly strengthen their security and resilience posture by prioritizing the remediation of the vulnerabilities listed in the KEV catalog as well.

This object may also contain up to seven objects with additional nested information. The cveTags, description, metrics, weaknesses, configurations, references, and vendorComments objects are explained in more detail below.

[cveTags optional](https://nvd.nist.gov/developers/vulnerabilities)
This object contains one or more tags that provide contextual information about the CVE.

source identifies the organization that provided the CVE Tag information and tags identifies each relevant CVE Tag.

Toggle JSON

```
"cveTags": [
	{
		"sourceIdentifier": "[email protected]",
		"tags": [
			"disputed"
		]
	}
],
```
[descriptions required](https://nvd.nist.gov/developers/vulnerabilities)
This object contains a description of the CVE in one or more languages. ISO 639-1:2002's two-letter language identifiers indicate the language of the description. Spanish language translations are provided by the [Spanish National Cybersecurity Institute](https://www.incibe.es/en) (INCIBE).

Toggle JSON

```
"descriptions": [
	{
		"lang": "en",
		"value": "The debug command in Sendmail is enabled, allowing attackers to execute commands as root."
	},
	{
		"lang": "es",
		"value": "El comando de depuración de Sendmail está activado, permitiendo a atacantes ejecutar comandos como root."
	}
],
```
[metrics optional](https://nvd.nist.gov/developers/vulnerabilities)
This object contains information on the CVE's impact. If the CVE has been analyzed, this object will contain any CVSSv2 or CVSSv3 information associated with the vulnerability.

source identifies the organization that provided the metrics information and type identifies whether the organization is a primary or secondary source. Primary sources include the NVD and CNA who have reached the provider level in CVMAP. 10% of provider level submissions are audited by the NVD. If a submission has been audited the NVD will appear as the primary source and the provider level CNA will appear as the secondary source.

Toggle JSON

```
"metrics": {
	"cvssMetricV2": [
		{
			"source": "[email protected]",
			"type": "Primary",
			"cvssData": {
				"version": "2.0",
				"vectorString": "AV:N/AC:L/Au:N/C:C/I:C/A:C",
				"accessVector": "NETWORK",
				"accessComplexity": "LOW",
				"authentication": "NONE",
				"confidentialityImpact": "COMPLETE",
				"integrityImpact": "COMPLETE",
				"availabilityImpact": "COMPLETE",
				"baseScore": 10.0				
			},
			"baseSeverity": "HIGH",
			"exploitabilityScore": 10.0,
			"impactScore": 10.0,
			"acInsufInfo": false,
			"obtainAllPrivilege": true,
			"obtainUserPrivilege": false,
			"obtainOtherPrivilege": false,
			"userInteractionRequired": false
		}
	]
},
```
[weaknesses optional](https://nvd.nist.gov/developers/vulnerabilities)
This object contains information on [specific weaknesses](https://nvd.nist.gov/vuln/categories), considered the cause of the vulnerability. Please note, a CVE that is Awaiting Enrichment, Undergoing Enrichment, or Rejected may not include the weaknesses object.

source identifies the organization that provided the weakness information and type identifies whether the organization is a primary or secondary source. Primary sources include the NVD and CNA who have reached the provider level in CVMAP. 10% of provider level submissions are audited by the NVD. If a submission has been audited the NVD will appear as the primary source and the provider level CNA will appear as the secondary source.

Toggle JSON

```
"weaknesses": [
	{
		"source": "[email protected]",
		"type": "Primary",
		"description": [
			{
				"lang": "en",
				"value": "NVD-CWE-Other"
			}
		]
	}
],
```
[configurations optional](https://nvd.nist.gov/developers/vulnerabilities)
This object contains the CVE applicability statements that convey which product, or products, are associated with the vulnerability according to the NVD analysis. Please note, a CVE that is Awaiting Enrichment, Undergoing Enrichment, or Rejected will not include the configurations object.

Like the JSON response, configurations are a hierarchical data structure that always contain one or more CPE match strings. Each object within configurations includes either an OR- or an AND-operator (and in rare cases a NEGATE flag) to covey the logical relationship of the CPE or child objects within. For example, if the vulnerability exists only when both CPE products are present, the operator is “AND”. If the vulnerability exists if either CPE is present, then the operator is “OR”.

The cpeMatch object contains the CPE Match Criteria, the criteria's unique identifier, and a statement of whether the criteria is vulnerable. The matchCriteriaId's corresponding `{uuid}` may be used with either the [Match Criteria API's matchCriteriaId](https://nvd.nist.gov/developers/products#cpematch-matchCriteriaId) or the [CPE API's matchCriteriaId](https://nvd.nist.gov/developers/products#cpes-matchCriteriaId) parameters.

Toggle JSON

```
"configurations": [
	{
		"nodes": [
			{
				"operator": "OR",
				"negate": false,
				"cpeMatch": [
					{
						"vulnerable": true,
						"criteria": "cpe:2.3:a:eric_allman:sendmail:5.58:*:*:*:*:*:*:*",
						"matchCriteriaId": "1D07F493-9C8D-44A4-8652-F28B46CBA27C"
					}
				]
			}
		]
	}
],
```
[references required](https://nvd.nist.gov/developers/vulnerabilities)
This object contains supplemental information relevant to the vulnerability, and may include details that are not present in the CVE Description. Each reference within this object provides one or more resource tags (e.g., third-party advisory, vendor advisory, technical paper, press/media, VDB entries). Resource tags are designed to categorize the type of information each reference contains.

source identifies the organization that provided the reference information and type identifies whether the organization is a primary or secondary source. Primary sources include the NVD and CNA who have reached the provider level in CVMAP. 10% of provider level submissions are audited by the NVD. If a submission has been audited, the NVD will appear as the primary source and the provider level CNA will appear as the secondary source.

Toggle JSON

```
"references": [
	{
		"url": "http://seclists.org/fulldisclosure/2019/Jun/16",
		"source": "[email protected]"
	},
	{
		"url": "http://www.openwall.com/lists/oss-security/2019/06/05/4",
		"source": "[email protected]"
	},
	{
		"url": "http://www.openwall.com/lists/oss-security/2019/06/06/1",
		"source": "[email protected]"
	},
	{
		"url": "http://www.securityfocus.com/bid/1",
		"source": "[email protected]"
	}
]
```
[vendorComments optional](https://nvd.nist.gov/developers/vulnerabilities)
This object contains any Official Vendor Comment for the CVE. NVD provides a service whereby organizations can submit Official Vendor Comments for CVE associated with their products. Organizations can use the service in a variety of ways. For example, they can provide configuration and remediation guidance, clarify vulnerability applicability, provide deeper vulnerability analysis, dispute third party vulnerability information, and explain vulnerability impact. Official Vendor Comments can be submitted to the NVD by email at [[email protected]](https://nvd.nist.gov/cdn-cgi/l/email-protection#4d233b290d23243e39632a223b). More information is provided on the [vendor comments](https://nvd.nist.gov/vuln/vendor-comments) page.

Toggle JSON

```
"vendorComments": [
	{
		"organization": "Red Hat",
		"comment": "Not vulnerable. This issue did not affect the versions of the util-linux packages (providing /bin/login), as shipped with Red Hat Enterprise Linux 2.1, 3, 4 or 5.",
		"lastModified": "2008-12-18T00:00:00"
	}
]
```

### CVE Change History API

The CVE Change History API is used to easily retrieve information on changes made to a single CVE or a collection of CVE from the NVD. This API provides additional transparency to the work of the NVD, allowing users to easily monitor when and why vulnerabilities change.

The NVD has existed in some form [since 1999](https://nvd.nist.gov/general/brief-history) and the fidelity of this information has changed several times over the decades. Earlier records may not contain the level of detail available with more recent CVE records. This is most apparent on CVE records prior to 2015.

The URL stem for retrieving CVE information is shown below.

Base URL

`https://services.nvd.nist.gov/rest/json/cvehistory/2.0`

#### [Parameters](https://nvd.nist.gov/developers/vulnerabilities)

[changeStartDate & changeEndDate optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{start date}`
*   `{end date}`

These parameters return any CVE that changed during the specified period. Please note, this is different from the last modified date parameters used with other APIs. If filtering by the change date, both `changeStartDate` and `changeEndDate` are required. The maximum allowable range when using any date range parameters is 120 consecutive days.

Values must be entered in the extended ISO-8601 date/time format:

`[YYYY][“-”][MM][“-”][DD][“T”][HH][“:”][MM][“:”][SS][Z]`
The "T" is a literal to separate the date from the time. The Z indicates an optional offset-from-UTC. Please note, if a positive Z value is used (such as +01:00 for Central European Time) then the "+" should be encoded in the request as "%2B". The user agent may handle this encoding automatically.

Request all CVE change histories between the start and end datetimes

`https://services.nvd.nist.gov/rest/json/cvehistory/2.0/?changeStartDate=2021-08-04T13:00:00.000%2B01:00&changeEndDate=2021-10-22T13:36:00.000%2B01:00`
[cveId optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{CVE-ID}`

This parameter returns the complete change history for a specific vulnerability identified by its unique Common Vulnerabilities and Exposures identifier (the CVE ID). `cveId` will not accept `{CVE-ID}` for vulnerabilities not yet published in the NVD.

Request the change history for a specific CVE using its CVE-ID

`https://services.nvd.nist.gov/rest/json/cvehistory/2.0?cveId=CVE-2019-1010218`
[eventName optional](https://nvd.nist.gov/developers/vulnerabilities) * `CVE Received`An approved source has published the CVE record to the CVE List and the NVD has processed the record and any supported data types. NVD analysis has not yet occurred on the CVE record. * `Initial Analysis`The NVD performs its initial analysis to enrich the CVE record with reference tags, CVSS base metrics, CWE, and CPE applicability statements. * `Reanalysis`The NVD performs further analysis resulting in some modification to the CVE record. * `CVE Modified`An approved source modifies a CVE record published in the NVD. The modification's source is identified on the details page in the event name and in the API response by the value of the sourceIdentifier. * `Modified Analysis`After an approved source modified a previously analyzed CVE record, the NVD performs further analysis. * `CVE Translated`An approved translator provides a non-English translation for the CVE record. * `Vendor Comment`The NVD updates the CVE record with additional information from the product vendor. * `CVE Source Update`The NVD updates the information on a source that contributed to the CVE record. * `CPE Deprecation Remap`The NVD updates the match criteria associated with the CVE record based on changes to the CPE dictionary. This event occurs separate from analysis. * `CWE Remap`The NVD updates the weakness associated with the CVE record. This event occurs separate from analysis. * `Reference Tag Update`The NVD updates the Reference Tag of a URL associated with the CVE record. This event occurs separate from analysis. * `CVE Rejected`An approved source rejects a CVE record. Rejections occurs for one or more reasons, including duplicate CVE entries, withdraw by the original requester, incorrect assignment, or some other administrative reason. * `CVE Unrejected`An approved source re-published a CVE record previously marked rejected. * `CVE CISA KEV Update`An update to CISA KEV information was performed for an associated CVE. This parameter returns all CVE associated with a specific type of change event. Please note, each request can contain only one value for the `eventName` parameter. Empty spaces in the URL should be encoded in the request as "%20". The user agent may handle this encoding automatically. Request all CVE that were rejected in the specified time frame `https://services.nvd.nist.gov/rest/json/cvehistory/2.0?eventName=CVE%20Rejected&changeStartDate=2021-08-04T13:00:00.000%2B01:00&changeEndDate=2021-10-22T13:36:00.000%2B01:00`
[resultsPerPage optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{page limit}`

This parameter specifies the maximum number of change events to be returned in a single API response. For network considerations, the default value and maximum allowable limit is 5,000.
[startIndex optional](https://nvd.nist.gov/developers/vulnerabilities)
*   `{offset}`

This parameter specifies the index of the first change events to be returned in the response data. The index is zero-based, meaning the first change events is at index zero.

The CVE Change History API returns four primary objects in the response body that are used for pagination: resultsPerPage, startIndex, totalResults, and cveChanges. totalResults indicates the total number of change events that match the request parameters. If the value of totalResults is greater than the value of resultsPerPage, there are more events than could be returned by a single API response and additional requests must update the `startIndex` to get the remaining events.

Request 20 change events, beginning at index 0 and ending at index 19

`https://services.nvd.nist.gov/rest/json/cvehistory/2.0/?resultsPerPage=20&startIndex=0`

#### [Response](https://nvd.nist.gov/developers/vulnerabilities)

##### CVE Change History API JSON Schema

This API response includes only one JSON schema for defining the structure of the response data. The following document includes information on data types, regex patterns, maximum character length, and similar information that can support developers and database administrators looking to create their own local repository.

*   [CVE Change History API Schema](https://csrc.nist.gov/schema/nvd/api/2.0/cve_history_api_json_2.0.schema)

##### Response Details

The CVE Change History API returns seven primary objects in the body of the response: resultsPerPage, startIndex, totalResults, format, version, timestamp, and cveChanges.

The totalResults object indicates the number of change events that match the request, including all parameters. If the value of totalResults is greater than the value of resultsPerPage, then additional requests are necessary to return the remaining records. The parameter startIndex may be used in subsequent requests to identify the starting point for the next request. More information and the best practices for using resultsPerPage and startIndex are described above.

The format and version objects identify the format and version of the API response. timestamp identifies when the response was generated.

The cveChanges object contains an array of objects equal to the number of change events returned in the response and is sorted in ascending order by the created property of the change object. The change object is explained in more detail below.

JSON response objects are either optional or required. Required response objects are always returned by the API and may contain fields without data. Optional response objects are only returned when they contain data.

##### change  required

This object contains the following required data: the CVE-ID, the type of change event, a Universally Unique Identifier (UUID) for the change event, the [source](https://nvd.nist.gov/developers/data-sources) of the change event, the date and time that the CVE was modified, and an array of data containing any additional details.

The details array is a required object. It will appear whether or not the array contains additional data.

Toggle JSON

```
{
	"resultsPerPage": 1,
	"startIndex": 0,
	"totalResults": 558843,
	"format": "NVD_CVEHistory",
	"version": "2.0",
	"timestamp": "2022-10-24T12:30:00.000",
	"cveChanges": [
		{
			"change": {
				"cveId": "CVE-2020-12448",
				"eventName": "Initial Analysis",
				"cveChangeId": "5DEF54B9-7FF3-4436-9763-2958C5B78731",
				"sourceIdentifier": "[email protected]",
				"created": "2020-05-11T15:05:30.490",
				"details": [
					{
						"action": "Added",
						"type": "CVSS V2",
						"newValue": "NIST (AV:N/AC:L/Au:N/C:P/I:N/A:N)"
					},
					{
						"action": "Added",
						"type": "CVSS V3.1",
						"newValue": "NIST AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N"
					},
					{
						"action": "Changed",
						"type": "Reference Type",
						"oldValue": "https://about.gitlab.com/blog/categories/releases/ No Types Assigned",
						"newValue": "https://about.gitlab.com/blog/categories/releases/ Product, Release Notes"
					},
					{
						"action": "Changed",
						"type": "Reference Type",
						"oldValue": "https://about.gitlab.com/releases/2020/04/30/security-release-12-10-2-released/ No Types Assigned",
						"newValue": "https://about.gitlab.com/releases/2020/04/30/security-release-12-10-2-released/ Release Notes, Vendor Advisory"
					},
					{
						"action": "Added",
						"type": "CWE",
						"newValue": "NIST CWE-22"
					},
					{
						"action": "Added",
						"type": "CPE Configuration",
						"newValue": "OR\n     *cpe:2.3:a:gitlab:gitlab:*:*:*:*:enterprise:*:*:* versions from (including) 12.8.0 up to (excluding) 12.8.10"
					}
				]
			}
		}
	]
}
```

Questions, comments, or concerns may be shared with the NVD by emailing [[email protected]](https://nvd.nist.gov/cdn-cgi/l/email-protection#d9b7afbd99b7b0aaadf7beb6af)

 Created September 20, 2022,  Updated February 25, 2025

*   [_X_ (link is external)](https://x.com/NISTCyber)
*   [_facebook_ (link is external)](https://www.facebook.com/NIST)
*   [_linkedin_ (link is external)](https://www.linkedin.com/company/nist)
*   [_youtube_ (link is external)](https://www.youtube.com/user/USNISTGOV)
*   [_rss_](https://www.nist.gov/news-events/nist-rss-feeds)
*   [_govdelivery_ (link is external)](https://public.govdelivery.com/accounts/USNIST/subscriber/new?qsp=USNIST_3)

[![Image 7: National Institute of Standards and Technology logo](https://nvd.nist.gov/site-media/images/nist/nist-logo.png)](https://nvd.nist.gov/developers/vulnerabilities "National Institute of Standards and Technology")

[![Image 8: National Institute of Standards and Technology logo](https://nvd.nist.gov/site-media/images/nist/nist-logo.png)](https://www.nist.gov/ "National Institute of Standards and Technology")

**HEADQUARTERS**

 100 Bureau Drive 

 Gaithersburg, MD 20899 

[(301) 975-2000](tel:301-975-2000)

[Webmaster](https://nvd.nist.gov/cdn-cgi/l/email-protection#3b554d5f7b5552484f155c544d) | [Contact Us](https://www.nist.gov/about-nist/contact-us) | [Our Other Offices](https://www.nist.gov/about-nist/visit)

**Incident Response Assistance and Non-NVD Related

Technical Cyber Security Questions:**

 US-CERT Security Operations Center 

 Email: [[email protected]](https://nvd.nist.gov/cdn-cgi/l/email-protection#790a161a390c0a541a1c0b0d571e160f)

 Phone: 1-888-282-0870 

[Site Privacy](https://www.nist.gov/oism/site-privacy) | [Accessibility](https://www.nist.gov/oism/accessibility) | [Privacy Program](https://www.nist.gov/privacy) | [Copyrights](https://www.nist.gov/oism/copyrights) | [Vulnerability Disclosure](https://www.commerce.gov/vulnerability-disclosure-policy) | [No Fear Act Policy](https://www.nist.gov/no-fear-act-policy) | [FOIA](https://www.nist.gov/foia) | [Environmental Policy](https://www.nist.gov/environmental-policy-statement) | [Scientific Integrity](https://www.nist.gov/summary-report-scientific-integrity) | [Information Quality Standards](https://www.nist.gov/nist-information-quality-standards) | [Commerce.gov](https://www.commerce.gov/) | [Science.gov](https://www.science.gov/) | [USA.gov](https://www.usa.gov/)
