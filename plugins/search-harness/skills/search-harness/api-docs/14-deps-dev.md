---
source: API | Open Source Insights
url: https://docs.deps.dev/api/v3/
final_url: https://docs.deps.dev/api/v3/
language: en
fetched_at: 2026-05-04
bytes: 57136
---

# API | Open Source Insights

> 

# deps.dev API

## Overview

The deps.dev API provides access to Open Source Insights data. It can be used by tool builders, researchers, and tinkerers who want to answer questions like:

* What versions are available for this package?
* What are the licenses that cover this version of a package?
* How many dependencies does this package have? What are they?
* What versions of what packages correspond to this file?

The API can be accessed in two ways: as JSON over HTTP, which is described on this page, as well as via gRPC. For more information about accessing the API via gRPC, please visit github.com/google/deps.dev.

## Using the API

You can access the API using any HTTP client. To quickly get started, you can
use the

```
curl
```

command-line tool.

The methods of the API accept parameters. For methods that use the HTTP GET verb, required parameters are passed as part of the request path, while optional parameters are passed as part of the query string.

All path and query parameters must be encoded so that they can be safely
included in a URL, by replacing special characters (e.g.

```
/
```

) with their
percent-encoded forms (e.g.

```
%2F
```

). How this is done depends on your
programming language of choice, but as an example, path parameters can be
encoded using encodeURIComponent in JavaScript or url.PathEscape
in Go, while for query parameters you could use URLSearchParams in
JavaScript or url.Values in Go.

For example, to get information about the npm package

```
@colors/colors
```

(note
that the

```
@
```

and

```
/
```

in the package name have been percent-encoded):

```
```
curl 'https://api.deps.dev/v3/systems/npm/packages/%40colors%2Fcolors'
```
```

### Data parameters

Parameters representing data blobs, such as hash values, are passed as base64 strings.

For example, to use the Query API method to look up package versions by file
content hash (note that the

```
/
```

and

```
=
```

have been percent-encoded):

```
```
curl 'https://api.deps.dev/v3alpha/query?hash.type=SHA1&hash.value=ulXBPXrC%2FUTfnMgHRFVxmjPzdbk%3D'
```
```

To compute a base64-encoded hash from a file’s contents suitable for use as a

```
hash.value
```

query parameter you can use the

```
openssl
```

and

```
base64
```

commands:

```
```
openssl sha1 -binary <file> | base64
```
```

### Package names

In general, the API refers to packages by the names used within their ecosystem, including details such as capitalization.

Exceptions:

* Maven names are of the form

  ```
  <group ID>:<artifact ID>
  ```

  , for example

  ```
  org.apache.logging.log4j:log4j-core
  ```

  .
* PyPI names are normalized as per PEP 503.
* NuGet names are normalized through lowercasing according to the Package Content API request parameter specification. Versions are normalized according to NuGet 3.4+ rules.

### Coverage

In general, the service collects all publicly-available data from each source (for example, it gathers all npm packages hosted by registry.npmjs.org).

Exceptions:

* For Maven packages, in addition to Maven Central, it gathers artifacts from the Jenkins, Gradle Plugins, and Google registries.
* For PyPI it only collects packages released as wheels and sdists.
* For Go it only collects modules that have been fetched through proxy.golang.org, and those declared as dependencies by those modules.
* For projects hosted on GitHub, GitLab, and Bitbucket it only gathers projects associated with a package otherwise known to the service.

## API reference

### GetPackage

```
GET /v3/systems/{packageKey.system}/packages/{packageKey.name}
```

GetPackage returns information about a package, including a list of its available versions, with the default version marked if known.

Example:

```
/v3/systems/npm/packages/%40colors%2Fcolors
```

#### Path parameters

* packageKey.system: string
* The package management system containing the package.

  Can be one of

  ```
  GO
  ```

  ,

  ```
  RUBYGEMS
  ```

  ,

  ```
  NPM
  ```

  ,

  ```
  CARGO
  ```

  ,

  ```
  MAVEN
  ```

  ,

  ```
  PYPI
  ```

  ,

  ```
  NUGET
  ```

  .
* packageKey.name: string
* The name of the package.

#### Response

* packageKey: object
* The name of the package. Note that it may differ from the name in the request, due to canonicalization.
* packageKey.system: string
* The package management system containing the package.

  Can be one of

  ```
  GO
  ```

  ,

  ```
  RUBYGEMS
  ```

  ,

  ```
  NPM
  ```

  ,

  ```
  CARGO
  ```

  ,

  ```
  MAVEN
  ```

  ,

  ```
  PYPI
  ```

  ,

  ```
  NUGET
  ```

  .
* packageKey.name: string
* The name of the package.
* versions[]: object[]
* The available versions of the package.
* versions[].versionKey: object
* The name of the version. Note that the package name may differ from the name in the request, due to canonicalization.
* versions[].versionKey.system: string
* The package management system containing the package.

  Can be one of

  ```
  GO
  ```

  ,

  ```
  RUBYGEMS
  ```

  ,

  ```
  NPM
  ```

  ,

  ```
  CARGO
  ```

  ,

  ```
  MAVEN
  ```

  ,

  ```
  PYPI
  ```

  ,

  ```
  NUGET
  ```

  .
* versions[].versionKey.name: string
* The name of the package.
* versions[].versionKey.version: string
* The version of the package.
* versions[].publishedAt: string
* The time when this package version was published, if available, as reported by the package management authority.
* versions[].isDefault: boolean
* If true, this is the default version of the package: the version that is installed when no version is specified. The precise meaning of this is system-specific, but it is commonly the version with the greatest version number, ignoring pre-release versions.
* versions[].isDeprecated: boolean
* If true, this version has been marked as deprecated.
* versions[].deprecatedReason: string
* The reason why this version is deprecated.

### GetVersion

```
GET /v3/systems/{versionKey.system}/packages/{versionKey.name}/versions/{versionKey.version}
```

GetVersion returns information about a specific package version, including its licenses and any security advisories known to affect it.

Example:

```
/v3/systems/npm/packages/%40colors%2Fcolors/versions/1.5.0
```

#### Path parameters

* versionKey.system: string
* The package management system containing the package.

  Can be one of

  ```
  GO
  ```

  ,

  ```
  RUBYGEMS
  ```

  ,

  ```
  NPM
  ```

  ,

  ```
  CARGO
  ```

  ,

  ```
  MAVEN
  ```

  ,

  ```
  PYPI
  ```

  ,

  ```
  NUGET
  ```

  .
* versionKey.name: string
* The name of the package.
* versionKey.version: string
* The version of the package.

#### Response

* versionKey: object
* The name of the package version. Note that the package and version name may differ from names specified in requests, if applicable, due to canonicalization.
* versionKey.system: string
* The package management system containing the package.

  Can be one of

  ```
  GO
  ```

  ,

  ```
  RUBYGEMS
  ```

  ,

  ```
  NPM
  ```

  ,

  ```
  CARGO
  ```

  ,

  ```
  MAVEN
  ```

  ,

  ```
  PYPI
  ```

  ,

  ```
  NUGET
  ```

  .
* versionKey.name: string
* The name of the package.
* versionKey.version: string
* The version of the package.
* publishedAt: string
* The time when this package version was published, if available, as reported by the package management authority.
* isDefault: boolean
* If true, this is the default version of the package: the version that is installed when no version is specified. The precise meaning of this is system-specific, but it is commonly the version with the greatest version number, ignoring pre-release versions.
* isDeprecated: boolean
* If true, this version has been marked as deprecated.
* deprecatedReason: string
* The reason why this version is deprecated.
* licenses[]: string[]
* The licenses governing the use of this package version.

  We identify licenses as SPDX 2.1 expressions. When there is no associated SPDX identifier, we identify a license as “non-standard”. When we are unable to obtain license information, this field is empty. When more than one license is listed, their relationship is unspecified.

  For Cargo, Maven, npm, NuGet, PyPI, and RubyGems, license information is read from the package metadata. For Go, license information is determined using the licensecheck package.

  License information is not intended to be legal advice, and you should independently verify the license or terms of any software for your own needs.
* advisoryKeys[]: object[]
* Security advisories known to affect this package version directly. Further information can be requested using the Advisory method.

  Note that this field does not include advisories that affect dependencies of this package version.
* advisoryKeys[].id: string
* The OSV identifier for the security advisory.
* links[]: object[]
* Links declared by or derived from package version metadata, to external web resources such as a homepage or source code repository. Note that these links are not verified for correctness.
* links[].label: string
* A label describing the resource that the link points to.
* links[].url: string
* The URL of the link.
* slsaProvenances[]: object[]
* SLSA provenance information for this package version. Extracted from a SLSA provenance attestation. This is only populated for npm package versions. See the ‘attestations’ field for more attestations (including SLSA provenance) for all systems.
* slsaProvenances[].sourceRepository: string
* The source code repository used to build the version.
* slsaProvenances[].commit: string
* The commit of the source code repository the version was built from.
* slsaProvenances[].url: string
* The URL of the provenance statement if there is one.
* slsaProvenances[].verified: boolean
* The Sigstore bundle containing this attestation was verified using the sigstore-go library.
* attestations[]: object[]
* Attestations for this package version.
* attestations[].type: string
* The type of attestation. One of https://slsa.dev/provenance/v0.2, https://slsa.dev/provenance/v1, https://docs.pypi.org/attestations/publish/v1.
* attestations[].url: string
* The URL of the attestation if there is one.
* attestations[].verified: boolean
* The attestation has been cryptographically verified by deps.dev. For attestations distributed in a Sigstore bundle, this field indicates the bundle was verified using the sigstore-go library.
* attestations[].sourceRepository: string
* Only set if type is https://slsa.dev/provenance/v0.2, https://slsa.dev/provenance/v1, https://docs.pypi.org/attestations/publish/v1. The source code repository used to build the version.
* attestations[].commit: string
* The commit of the source code repository the version was built from.
* registries[]: string[]
* URLs for the package management registries this package version is available from. Only set for systems that use a central repository for package distribution: Cargo, Maven, npm, NuGet, PyPI, and RubyGems.
* relatedProjects[]: object[]
* Projects that are related to this package version.
* relatedProjects[].projectKey: object
* The identifier for the project.
* relatedProjects[].projectKey.id: string
* A project identifier of the form

  ```
  github.com/user/repo
  ```

  ,

  ```
  gitlab.com/user/repo
  ```

  , or

  ```
  bitbucket.org/user/repo
  ```

  .
* relatedProjects[].relationProvenance: string
* How the mapping between project and package version was discovered.

  Can be one of

  ```
  SLSA_ATTESTATION
  ```

  ,

  ```
  GO_ORIGIN
  ```

  ,

  ```
  PYPI_PUBLISH_ATTESTATION
  ```

  ,

  ```
  RUBYGEMS_PUBLISH_ATTESTATION
  ```

  ,

  ```
  UNVERIFIED_METADATA
  ```

  .
* relatedProjects[].relationType: string
* What the relationship between the project and the package version is.

  Can be one of

  ```
  SOURCE_REPO
  ```

  ,

  ```
  ISSUE_TRACKER
  ```

  .
* projectStatus: object
* Whether a project is actively maintained, deprecated, etc. This field is not set for any package version outside of the PyPI system. See https://packaging.python.org/en/latest/specifications/project-status-markers/#project-status-markers for more information.
* projectStatus.status: string
* projectStatus.reason: string

### GetRequirements

```
GET /v3/systems/{versionKey.system}/packages/{versionKey.name}/versions/{versionKey.version}:requirements
```

GetRequirements returns the requirements for a given version in a system-specific format. Requirements are currently available for Cargo, Go, Maven, npm, NuGet, PyPI, and RubyGems.

Requirements are the dependency constraints specified by the version.

Example:

```
/v3/systems/nuget/packages/castle.core/versions/5.1.1:requirements
```

#### Path parameters

* versionKey.system: string
* The package management system containing the package.

  Can be one of

  ```
  GO
  ```

  ,

  ```
  RUBYGEMS
  ```

  ,

  ```
  NPM
  ```

  ,

  ```
  CARGO
  ```

  ,

  ```
  MAVEN
  ```

  ,

  ```
  PYPI
  ```

  ,

  ```
  NUGET
  ```

  .
* versionKey.name: string
* The name of the package.
* versionKey.version: string
* The version of the package.

#### Response

* nuget: object
* The NuGet-specific representation of the version’s requirements.

  Note that the term “dependency” is used here to mean “a single unresolved requirement” to be consistent with how the term is used in the NuGet ecosystem. This is different to how it is used elsewhere in the deps.dev API.
* nuget.dependencyGroups[]: object[]
* The requirements grouped by target framework.
* nuget.dependencyGroups[].targetFramework: string
* The target framework that this dependency group is for.
* nuget.dependencyGroups[].dependencies[]: object[]
* The requirements belonging to this dependency group.
* nuget.dependencyGroups[].dependencies[].name: string
* The name of the package.
* nuget.dependencyGroups[].dependencies[].requirement: string
* The requirement on the package.
* nuget.dependencyGroups[].dependencies[].include: string
* nuget.dependencyGroups[].dependencies[].exclude: string
* nuget.targetFrameworks[]: string[]
* nuget.developmentDependency: boolean
* nuget.frameworkAssemblies[]: object[]
* nuget.frameworkAssemblies[].assemblyName: string
* nuget.frameworkAssemblies[].targetFramework: string
* nuget.frameworkReferences[]: object[]
* nuget.frameworkReferences[].name: string
* nuget.frameworkReferences[].targetFramework: string
* npm: object
* The npm-specific representation of the version’s requirements.

  Note that the term “dependency” is used here to mean “a single unresolved requirement” to be consistent with how the term is used in the npm ecosystem. This is different to how it is used elsewhere in the deps.dev API.
* npm.dependencies: object
* The dependency-related fields declared in the requested package version’s package.json.
* npm.dependencies.dependencies[]: object[]
* The “dependencies” field of a package.json, represented as a list of name, requirement pairs.
* npm.dependencies.dependencies[].name: string
* The name of the package, the key in the original object.
* npm.dependencies.dependencies[].requirement: string
* The requirement, the corresponding value from the original object.
* npm.dependencies.devDependencies[]: object[]
* The “devDependencies” field of a package.json. The format is the same as “dependencies”.
* npm.dependencies.devDependencies[].name: string
* The name of the package, the key in the original object.
* npm.dependencies.devDependencies[].requirement: string
* The requirement, the corresponding value from the original object.
* npm.dependencies.optionalDependencies[]: object[]
* The “optionalDependencies” field of a package.json. The format is the same as “dependencies”.
* npm.dependencies.optionalDependencies[].name: string
* The name of the package, the key in the original object.
* npm.dependencies.optionalDependencies[].requirement: string
* The requirement, the corresponding value from the original object.
* npm.dependencies.peerDependencies[]: object[]
* The “peerDependencies” field of a package.json. The format is the same as “dependencies”.
* npm.dependencies.peerDependencies[].name: string
* The name of the package, the key in the original object.
* npm.dependencies.peerDependencies[].requirement: string
* The requirement, the corresponding value from the original object.
* npm.dependencies.bundleDependencies[]: string[]
* The “bundleDependencies” field of a package.json: a list of package names. In the package.json this may also just be the boolean value “true”, in which case this field will contain the names of all the dependencies from the “dependencies” field.
* npm.dependencies.peerDependencyMetadata[]: object[]
* The “peerDependencyMetadata” field of a package.json. A list of peer dependency names that may be marked optional.
* npm.dependencies.peerDependencyMetadata[].name: string
* The name of the package from the peerDependencies field.
* npm.dependencies.peerDependencyMetadata[].optional: boolean
* Whether the connection is marked optional inside peerDependenciesMeta.
* npm.bundled[]: object[]
* Contents of any additional package.json files found inside the “node\_modules” folder of the version’s tarball, including nested “node\_modules”.
* npm.bundled[].path: string
* The path inside the tarball where this dependency was found.
* npm.bundled[].name: string
* The name of the bundled package, as declared inside the bundled package.json.
* npm.bundled[].version: string
* The version of this package, as declared inside the bundled package.json.
* npm.bundled[].dependencies: object
* The dependency-related fields from the bundled package.json.
* npm.bundled[].dependencies.dependencies[]: object[]
* The “dependencies” field of a package.json, represented as a list of name, requirement pairs.
* npm.bundled[].dependencies.dependencies[].name: string
* The name of the package, the key in the original object.
* npm.bundled[].dependencies.dependencies[].requirement: string
* The requirement, the corresponding value from the original object.
* npm.bundled[].dependencies.devDependencies[]: object[]
* The “devDependencies” field of a package.json. The format is the same as “dependencies”.
* npm.bundled[].dependencies.devDependencies[].name: string
* The name of the package, the key in the original object.
* npm.bundled[].dependencies.devDependencies[].requirement: string
* The requirement, the corresponding value from the original object.
* npm.bundled[].dependencies.optionalDependencies[]: object[]
* The “optionalDependencies” field of a package.json. The format is the same as “dependencies”.
* npm.bundled[].dependencies.optionalDependencies[].name: string
* The name of the package, the key in the original object.
* npm.bundled[].dependencies.optionalDependencies[].requirement: string
* The requirement, the corresponding value from the original object.
* npm.bundled[].dependencies.peerDependencies[]: object[]
* The “peerDependencies” field of a package.json. The format is the same as “dependencies”.
* npm.bundled[].dependencies.peerDependencies[].name: string
* The name of the package, the key in the original object.
* npm.bundled[].dependencies.peerDependencies[].requirement: string
* The requirement, the corresponding value from the original object.
* npm.bundled[].dependencies.bundleDependencies[]: string[]
* The “bundleDependencies” field of a package.json: a list of package names. In the package.json this may also just be the boolean value “true”, in which case this field will contain the names of all the dependencies from the “dependencies” field.
* npm.bundled[].dependencies.peerDependencyMetadata[]: object[]
* The “peerDependencyMetadata” field of a package.json. A list of peer dependency names that may be marked optional.
* npm.bundled[].dependencies.peerDependencyMetadata[].name: string
* The name of the package from the peerDependencies field.
* npm.bundled[].dependencies.peerDependencyMetadata[].optional: boolean
* Whether the connection is marked optional inside peerDependenciesMeta.
* npm.os[]: string[]
* The operating systems that this package version can run on.
* npm.cpu[]: string[]
* The CPU architectures that this package version can run on.
* maven: object
* The Maven-specific representation of the version’s requirements.

  Note that the term “dependency” is used here to mean “a single unresolved requirement” to be consistent with how the term is used in the Maven ecosystem. This is different to how it is used elsewhere in the deps.dev API.

  This data is as it is declared in a version POM file. The data in parent POMs are not merged. Any string field may contain references to properties, and the properties are not interpolated.
* maven.parent: object
* The direct parent of a package version.
* maven.parent.system: string
* The package management system containing the package.

  Can be one of

  ```
  GO
  ```

  ,

  ```
  RUBYGEMS
  ```

  ,

  ```
  NPM
  ```

  ,

  ```
  CARGO
  ```

  ,

  ```
  MAVEN
  ```

  ,

  ```
  PYPI
  ```

  ,

  ```
  NUGET
  ```

  .
* maven.parent.name: string
* The name of the package.
* maven.parent.version: string
* The version of the package.
* maven.dependencies[]: object[]
* The list of dependencies.
* maven.dependencies[].name: string
* The name of the package.
* maven.dependencies[].version: string
* The version requirement of the dependency.
* maven.dependencies[].classifier: string
* The classifier of the dependency, which distinguishes artifacts that differ in content.
* maven.dependencies[].type: string
* The type of the dependency, defaults to jar.
* maven.dependencies[].scope: string
* The scope of the dependency, specifies how to limit the transitivity of a dependency.
* maven.dependencies[].optional: string
* Whether the dependency is optional or not.
* maven.dependencies[].exclusions[]: string[]
* The dependencies to be excluded, in the form of a list of package names. Exclusions may contain wildcards in both groupID and artifactID.
* maven.dependencies[].resolvedVersion: string
* The resolved instances of the above version/name fields. I.e. If the version field contained a Maven property, then the resolved version will have the actual property’s value interpolated in.
* maven.dependencies[].resolvedName: string
* maven.dependencies[].origin: string
* The origin of the dependency. Can be any of the following values: “” - declared in the current package’s merged, effective POM. I.e. the POM formed from merging all the ancestor POMs. “parent” - this dependency represents the parent package’s POM. “management” - declared in a local or inherited

  section. “import” - declared in another BOM POM in thesection.</p> </dd>* maven.dependencyManagement[]: object[]

  The list of dependency management. The format is the same as dependencies.

  * maven.dependencyManagement[].name: string

  The name of the package.

  * maven.dependencyManagement[].version: string

  The version requirement of the dependency.

  * maven.dependencyManagement[].classifier: string

  The classifier of the dependency, which distinguishes artifacts that differ in content.

  * maven.dependencyManagement[].type: string

  The type of the dependency, defaults to jar.

  * maven.dependencyManagement[].scope: string

  The scope of the dependency, specifies how to limit the transitivity of a dependency.

  * maven.dependencyManagement[].optional: string

  Whether the dependency is optional or not.

  * maven.dependencyManagement[].exclusions[]: string[]

  The dependencies to be excluded, in the form of a list of package names. Exclusions may contain wildcards in both groupID and artifactID.

  * maven.dependencyManagement[].resolvedVersion: string

  The resolved instances of the above version/name fields. I.e. If the version field contained a Maven property, then the resolved version will have the actual property’s value interpolated in.

  * maven.dependencyManagement[].resolvedName: string
  * maven.dependencyManagement[].origin: string

  The origin of the dependency. Can be any of the following values: “” - declared in the current package’s merged, effective POM. I.e. the POM formed from merging all the ancestor POMs. “parent” - this dependency represents the parent package’s POM. “management” - declared in a local or inherited

  section. “import” - declared in another BOM POM in thesection.</p> </dd>* maven.properties[]: object[]

  The list of properties, used to resolve placeholders.

  * maven.properties[].name: string

  The name of the property.

  * maven.properties[].value: string

  The value of the property.

  * maven.repositories[]: object[]

  The list of repositories.

  * maven.repositories[].id: string

  The ID of the repository.

  * maven.repositories[].url: string

  The URL of the repository.

  * maven.repositories[].layout: string

  Whether the description of the repository follows a common layout.

  * maven.repositories[].releasesEnabled: string

  Whether the repository is enabled for release downloads.

  * maven.repositories[].snapshotsEnabled: string

  Whether the repository is enabled for snapshot downloads.

  * maven.repositories[].resolvedUrl: string

  The resolved instance of URL. I.e. If the URL contained a Maven property, then the resolved URL will have the actual property’s value interpolated in.

  * maven.profiles[]: object[]

  The list of profiles.

  * maven.profiles[].id: string

  The ID of the profile.

  * maven.profiles[].activation: object

  The activation requirement of the profile.

  * maven.profiles[].activation.activeByDefault: string

  Whether the profile is active by default.

  * maven.profiles[].activation.jdk: object

  The JDK requirement of the activation.

  * maven.profiles[].activation.jdk.jdk: string

  The JDK requirement to activate the profile.

  * maven.profiles[].activation.os: object

  The operating system requirement of the activation.

  * maven.profiles[].activation.os.name: string

  The name of the operating system.

  * maven.profiles[].activation.os.family: string

  The family of the operating system.

  * maven.profiles[].activation.os.arch: string

  The CPU architecture of the operating system,

  * maven.profiles[].activation.os.version: string

  The version of the operating system.

  * maven.profiles[].activation.property: object

  The property requirement of the activation.

  * maven.profiles[].activation.property.property: object

  The property requirement to activate the profile. This can be a system property or CLI user property.

  * maven.profiles[].activation.property.property.name: string

  The name of the property.

  * maven.profiles[].activation.property.property.value: string

  The value of the property.

  * maven.profiles[].activation.file: object

  The file requirement of the activation.

  * maven.profiles[].activation.file.exists: string

  The name of the file that its existence activates the profile.

  * maven.profiles[].activation.file.missing: string

  The name of the file, activate the profile if the file is missing.

  * maven.profiles[].dependencies[]: object[]

  The dependencies specified in the profile.

  * maven.profiles[].dependencies[].name: string

  The name of the package.

  * maven.profiles[].dependencies[].version: string

  The version requirement of the dependency.

  * maven.profiles[].dependencies[].classifier: string

  The classifier of the dependency, which distinguishes artifacts that differ in content.

  * maven.profiles[].dependencies[].type: string

  The type of the dependency, defaults to jar.

  * maven.profiles[].dependencies[].scope: string

  The scope of the dependency, specifies how to limit the transitivity of a dependency.

  * maven.profiles[].dependencies[].optional: string

  Whether the dependency is optional or not.

  * maven.profiles[].dependencies[].exclusions[]: string[]

  The dependencies to be excluded, in the form of a list of package names. Exclusions may contain wildcards in both groupID and artifactID.

  * maven.profiles[].dependencies[].resolvedVersion: string

  The resolved instances of the above version/name fields. I.e. If the version field contained a Maven property, then the resolved version will have the actual property’s value interpolated in.

  * maven.profiles[].dependencies[].resolvedName: string
  * maven.profiles[].dependencies[].origin: string

  The origin of the dependency. Can be any of the following values: “” - declared in the current package’s merged, effective POM. I.e. the POM formed from merging all the ancestor POMs. “parent” - this dependency represents the parent package’s POM. “management” - declared in a local or inherited

  section. “import” - declared in another BOM POM in thesection.</p> </dd>* maven.profiles[].dependencyManagement[]: object[]

  The dependency management specified in the profile.

  * maven.profiles[].dependencyManagement[].name: string

  The name of the package.

  * maven.profiles[].dependencyManagement[].version: string

  The version requirement of the dependency.

  * maven.profiles[].dependencyManagement[].classifier: string

  The classifier of the dependency, which distinguishes artifacts that differ in content.

  * maven.profiles[].dependencyManagement[].type: string

  The type of the dependency, defaults to jar.

  * maven.profiles[].dependencyManagement[].scope: string

  The scope of the dependency, specifies how to limit the transitivity of a dependency.

  * maven.profiles[].dependencyManagement[].optional: string

  Whether the dependency is optional or not.

  * maven.profiles[].dependencyManagement[].exclusions[]: string[]

  The dependencies to be excluded, in the form of a list of package names. Exclusions may contain wildcards in both groupID and artifactID.

  * maven.profiles[].dependencyManagement[].resolvedVersion: string

  The resolved instances of the above version/name fields. I.e. If the version field contained a Maven property, then the resolved version will have the actual property’s value interpolated in.

  * maven.profiles[].dependencyManagement[].resolvedName: string
  * maven.profiles[].dependencyManagement[].origin: string

  The origin of the dependency. Can be any of the following values: “” - declared in the current package’s merged, effective POM. I.e. the POM formed from merging all the ancestor POMs. “parent” - this dependency represents the parent package’s POM. “management” - declared in a local or inherited

  section. “import” - declared in another BOM POM in thesection.</p> </dd>* maven.profiles[].properties[]: object[]

  The properties specified in the profile.

  * maven.profiles[].properties[].name: string

  The name of the property.

  * maven.profiles[].properties[].value: string

  The value of the property.

  * maven.profiles[].repositories[]: object[]

  The repositories specified in the profile.

  * maven.profiles[].repositories[].id: string

  The ID of the repository.

  * maven.profiles[].repositories[].url: string

  The URL of the repository.

  * maven.profiles[].repositories[].layout: string

  Whether the description of the repository follows a common layout.

  * maven.profiles[].repositories[].releasesEnabled: string

  Whether the repository is enabled for release downloads.

  * maven.profiles[].repositories[].snapshotsEnabled: string

  Whether the repository is enabled for snapshot downloads.

  * maven.profiles[].repositories[].resolvedUrl: string

  The resolved instance of URL. I.e. If the URL contained a Maven property, then the resolved URL will have the actual property’s value interpolated in.

  * rubygems: object

  The RubyGems-specific representation of the version’s requirements.

  Note that the term “dependency” is used here to mean “a single unresolved requirement” to be consistent with how the term is used in the npm ecosystem. This is different to how it is used elsewhere in the deps.dev API.

  * rubygems.runtimeDependencies[]: object[]

  The list of runtime dependencies.

  * rubygems.runtimeDependencies[].name: string

  The name of the package.

  * rubygems.runtimeDependencies[].requirement: string

  The requirement on the package.

  * rubygems.devDependencies[]: object[]

  The list of development dependencies.

  * rubygems.devDependencies[].name: string

  The name of the package.

  * rubygems.devDependencies[].requirement: string

  The requirement on the package.

  * rubygems.platform: string

  Platform identifier for versions with platform specific code.

  * rubygems.requiredRubyVersion: string

  The required version of Ruby.

  * rubygems.requiredRubygemsVersion: string

  The required version of RubyGems.

  * go: object

  The Go-specific representation of the version’s requirements.

  Note that the term “dependency” is used here to mean “a single requirement” to be consistent with how the term is used in the Go ecosystem. This is different to how it is used elsewhere in the deps.dev API.

  * go.directDependencies[]: object[]
  * go.directDependencies[].name: string
  * go.directDependencies[].requirement: string
  * go.indirectDependencies[]: object[]
  * go.indirectDependencies[].name: string
  * go.indirectDependencies[].requirement: string
  * go.replaces[]: object[]

  Replace represents a replace directive in a go.mod file, which replaces the contents of a module with contents found elsewhere. See https://go.dev/ref/mod#go-mod-file-replace

  * go.replaces[].src: object

  The module to be replaced. The version (in the requirement field) is optional. If omitted, all versions of the module are replaced.

  * go.replaces[].src.name: string
  * go.replaces[].src.requirement: string
  * go.replaces[].replacement: object

  The replacement can either be another remote module (specifying name and version) or a path to a local module. Exactly one of replacement or local\_path will be set.

  * go.replaces[].replacement.name: string
  * go.replaces[].replacement.requirement: string
  * go.replaces[].localPath: string

  The path to a local directory containing the replacement module.

  * go.excludes[]: object[]

  Excludes represents exclude directives in a go.mod file, which specify versions of a module that are ignored. See https://go.dev/ref/mod#go-mod-file-exclude.

  Note: Before Go 1.16, excluded versions resulted in the next higher available version being silently chosen and not committed to go.mod, leading to non-deterministic builds. From Go 1.16 onwards, the substituting dependency must be explicitly captured in go.mod.

  * go.excludes[].name: string
  * go.excludes[].requirement: string
  * pypi: object

  The PyPI-specific representation of the version’s requirements.

  Note that the term “dependency” is used here to mean “a single requirement” to be consistent with how the term is used in the Python ecosystem. This is different to how it is used elsewhere in the deps.dev API.

  * pypi.dependencies[]: object[]
  * pypi.dependencies[].projectName: string
  * pypi.dependencies[].extras: string
  * pypi.dependencies[].versionSpecifier: string
  * pypi.dependencies[].environmentMarker: string
  * pypi.providedExtras[]: object[]
  * pypi.providedExtras[].name: string
  * pypi.externalDependencies[]: object[]
  * pypi.externalDependencies[].name: string
  * pypi.externalDependencies[].versionSpecifier: string
  * pypi.externalDependencies[].environmentMarker: string
  * pypi.requiredPythonVersion: string
  * cargo: object

  The Cargo-specific representation of a crate version’s requirements.

  Note that the term “dependency” is used here to mean “a single requirement” to be consistent with how the term is used in the Cargo ecosystem. This is different to how it is used elsewhere in the deps.dev API.

  * cargo.dependencies[]: object[]
  * cargo.dependencies[].name: string
  * cargo.dependencies[].requirement: string
  * cargo.dependencies[].kind: string

  Whether this is a normal dependency, dev-dependency, or build-dependency.

  * cargo.dependencies[].optional: boolean

  Whether this is an optional dependency.

  * cargo.dependencies[].packageAlias: string

  The name of the package as it is used in the source code.

  * cargo.dependencies[].usesDefaultFeatures: boolean

  Whether the dependency uses its default features.

  * cargo.dependencies[].features[]: string[]

  Features that are enabled on this dependency.

  * cargo.dependencies[].target: string

  If present, then this dependency is specific to a given platform.

  * cargo.features[]: object[]
  * cargo.features[].name: string
  * cargo.features[].implies[]: string[]
  </dl> ### GetDependencies `GET /v3/systems/{versionKey.system}/packages/{versionKey.name}/versions/{versionKey.version}:dependencies`

  List of other features or dependencies that this feature would then enable.

  GetDependencies returns a resolved dependency graph for the given package version. Dependencies are currently available for npm, Cargo, Maven and PyPI.

  Dependencies are the resolution of the requirements (dependency constraints) specified by a version.

  The dependency graph should be similar to one produced by installing the package version on a generic 64-bit Linux system, with no other dependencies present. The precise meaning of this varies from system to system.

  Example: [`/v3/systems/npm/packages/react/versions/18.2.0:dependencies`](https://api.deps.dev/v3/systems/npm/packages/react/versions/18.2.0:dependencies) #### Path parameters
  + versionKey.system: string
  + The package management system containing the package.

    Can be one of

    ```
    GO
    ```

    ,

    ```
    RUBYGEMS
    ```

    ,

    ```
    NPM
    ```

    ,

    ```
    CARGO
    ```

    ,

    ```
    MAVEN
    ```

    ,

    ```
    PYPI
    ```

    ,

    ```
    NUGET
    ```

    .
  + versionKey.name: string
  + The name of the package.
  + versionKey.version: string
  + The version of the package.
  + nodes[]: object[]
  + The nodes of the dependency graph. The first node is the root of the graph.
  + nodes[].versionKey: object
  + The package version represented by this node. Note that the package and version name may differ from the names in the request, if provided, due to canonicalization.

    In some systems, a graph may contain multiple nodes for the same package version.
  + nodes[].versionKey.system: string
  + The package management system containing the package.

    Can be one of

    ```
    GO
    ```

    ,

    ```
    RUBYGEMS
    ```

    ,

    ```
    NPM
    ```

    ,

    ```
    CARGO
    ```

    ,

    ```
    MAVEN
    ```

    ,

    ```
    PYPI
    ```

    ,

    ```
    NUGET
    ```

    .
  + nodes[].versionKey.name: string
  + The name of the package.
  + nodes[].versionKey.version: string
  + The version of the package.
  + nodes[].bundled: boolean
  + If true, this is a bundled dependency.

    For bundled dependencies, the package name in the version key encodes how the dependency is bundled. As an example, a bundled dependency with a name like “a>1.2.3>b>c” is part of the dependency graph of package “a” at version “1.2.3”, and has the local name “c”. It may or may not be the same as a package with the global name “c”.
  + nodes[].relation: string
  + Whether this node represents a direct or indirect dependency within this dependency graph. Note that it’s possible for a dependency to be both direct and indirect; if so, it is marked as direct.

    Can be one of

    ```
    SELF
    ```

    ,

    ```
    DIRECT
    ```

    ,

    ```
    INDIRECT
    ```

    .
  + nodes[].errors[]: string[]
  + Errors associated with this node of the graph, such as an unresolved dependency requirement. An error on a node may imply the graph as a whole is incorrect. These error messages have no defined format and are intended for human consumption.
  + edges[]: object[]
  + The edges of the dependency graph.
  + edges[].fromNode: number
  + The node declaring the dependency, specified as an index into the list of nodes.
  + edges[].toNode: number
  + The node resolving the dependency, specified as an index into the list of nodes.
  + edges[].requirement: string
  + The requirement resolved by this edge, as declared by the “from” node. The meaning of this field is system-specific. As an example, in npm, the requirement “^1.0.0” may be resolved by the version “1.2.3”.
  + error: string
  + Any error associated with the dependency graph that is not specific to a node. An error here may imply the graph as a whole is incorrect. This error message has no defined format and is intended for human consumption.

  GetProject returns information about projects hosted by GitHub, GitLab, or BitBucket, when known to us.

  Example: [`/v3/projects/github.com%2Ffacebook%2Freact`](https://api.deps.dev/v3/projects/github.com%2Ffacebook%2Freact) #### Path parameters
  + projectKey.id: string
  + A project identifier of the form

    ```
    github.com/user/repo
    ```

    ,

    ```
    gitlab.com/user/repo
    ```

    , or

    ```
    bitbucket.org/user/repo
    ```

    .
  + projectKey: object
  + The identifier for the project. Note that this may differ from the identifier in the request, due to canonicalization.
  + projectKey.id: string
  + A project identifier of the form

    ```
    github.com/user/repo
    ```

    ,

    ```
    gitlab.com/user/repo
    ```

    , or

    ```
    bitbucket.org/user/repo
    ```

    .
  + openIssuesCount: number
  + The number of open issues reported by the project host. Only available for GitHub and GitLab.
  + starsCount: number
  + The number of stars reported by the project host. Only available for GitHub and GitLab.
  + forksCount: number
  + The number of forks reported by the project host. Only available for GitHub and GitLab.
  + license: string
  + The license reported by the project host.
  + description: string
  + The description reported by the project host.
  + homepage: string
  + The homepage reported by the project host.
  + scorecard: object
  + An OpenSSF Scorecard for the project, if one is available.
  + scorecard.date: string
  + The date at which the scorecard was produced. The time portion of this field is midnight UTC.
  + scorecard.repository: object
  + The source code repository and commit the scorecard was produced from.
  + scorecard.repository.name: string
  + The source code repository the scorecard was produced from.
  + scorecard.repository.commit: string
  + The source code commit the scorecard was produced from.
  + scorecard.scorecard: object
  + The version and commit of the Scorecard program used to produce the scorecard.
  + scorecard.scorecard.version: string
  + The version of the Scorecard program used to produce the scorecard.
  + scorecard.scorecard.commit: string
  + The commit of the Scorecard program used to produce the scorecard.
  + scorecard.checks[]: object[]
  + The results of the Scorecard Checks performed on the project.
  + scorecard.checks[].name: string
  + The name of the check.
  + scorecard.checks[].documentation: object
  + Human-readable documentation for the check.
  + scorecard.checks[].documentation.shortDescription: string
  + A short description of the check.
  + scorecard.checks[].documentation.url: string
  + A link to more details about the check.
  + scorecard.checks[].score: number
  + A score in the range [0,10]. A higher score is better. A negative score indicates that the check did not run successfully.
  + scorecard.checks[].reason: string
  + The reason for the score.
  + scorecard.checks[].details[]: string[]
  + Further details regarding the check.
  + scorecard.overallScore: number
  + A weighted average score in the range [0,10]. A higher score is better.
  + scorecard.metadata[]: string[]
  + Additional metadata associated with the scorecard.
  + ossFuzz: object
  + Details of this project’s testing by the OSS-Fuzz service. Only set if the project is tested by OSS-Fuzz.
  + ossFuzz.lineCount: number
  + The total number of lines of code in the project.
  + ossFuzz.lineCoverCount: number
  + The number of lines of code covered by fuzzing.
  + ossFuzz.date: string
  + The date the fuzz test that produced the coverage information was run against this project. The time portion of this field is midnight UTC.
  + ossFuzz.configUrl: string
  + The URL containing the configuration for the project in the OSS-Fuzz repository.

  GetProjectPackageVersions returns known mappings between the requested project and package versions. At most 1500 package versions are returned. Mappings which were derived from attestations are served first.

  Example: [`/v3/projects/github.com%2Ffacebook%2Freact:packageversions`](https://api.deps.dev/v3/projects/github.com%2Ffacebook%2Freact:packageversions) #### Path parameters
  + projectKey.id: string
  + A project identifier of the form

    ```
    github.com/user/repo
    ```

    ,

    ```
    gitlab.com/user/repo
    ```

    , or

    ```
    bitbucket.org/user/repo
    ```

    .
  + versions[]: object[]
  + The versions that were built from the source code contained in this project.
  + versions[].versionKey: object
  + The identifier for the version.
  + versions[].versionKey.system: string
  + The package management system containing the package.

    Can be one of

    ```
    GO
    ```

    ,

    ```
    RUBYGEMS
    ```

    ,

    ```
    NPM
    ```

    ,

    ```
    CARGO
    ```

    ,

    ```
    MAVEN
    ```

    ,

    ```
    PYPI
    ```

    ,

    ```
    NUGET
    ```

    .
  + versions[].versionKey.name: string
  + The name of the package.
  + versions[].versionKey.version: string
  + The version of the package.
  + versions[].relationType: string
  + What the relationship between the project and the package version is.

    Can be one of

    ```
    SOURCE_REPO
    ```

    ,

    ```
    ISSUE_TRACKER
    ```

    .
  + versions[].relationProvenance: string
  + How the mapping between project and package version was discovered.

    Can be one of

    ```
    SLSA_ATTESTATION
    ```

    ,

    ```
    GO_ORIGIN
    ```

    ,

    ```
    PYPI_PUBLISH_ATTESTATION
    ```

    ,

    ```
    RUBYGEMS_PUBLISH_ATTESTATION
    ```

    ,

    ```
    UNVERIFIED_METADATA
    ```

    .
  + versions[].slsaProvenances[]: object[]
  + The SLSA provenance statements that link the version to the project. This is only populated for npm package versions. See the ‘attestations’ field for more attestations (including SLSA provenance) for all systems.
  + versions[].slsaProvenances[].sourceRepository: string
  + The source code repository used to build the version.
  + versions[].slsaProvenances[].commit: string
  + The commit of the source code repository the version was built from.
  + versions[].slsaProvenances[].url: string
  + The URL of the provenance statement if there is one.
  + versions[].slsaProvenances[].verified: boolean
  + The Sigstore bundle containing this attestation was verified using the sigstore-go library.
  + versions[].attestations[]: object[]
  + Attestations that link the version to the project.
  + versions[].attestations[].type: string
  + The type of attestation. One of https://slsa.dev/provenance/v0.2, https://slsa.dev/provenance/v1, https://docs.pypi.org/attestations/publish/v1.
  + versions[].attestations[].url: string
  + The URL of the attestation if there is one.
  + versions[].attestations[].verified: boolean
  + The attestation has been cryptographically verified by deps.dev. For attestations distributed in a Sigstore bundle, this field indicates the bundle was verified using the sigstore-go library.
  + versions[].attestations[].sourceRepository: string
  + Only set if type is https://slsa.dev/provenance/v0.2, https://slsa.dev/provenance/v1, https://docs.pypi.org/attestations/publish/v1. The source code repository used to build the version.
  + versions[].attestations[].commit: string
  + The commit of the source code repository the version was built from.

  GetAdvisory returns information about security advisories hosted by OSV.

  Example: [`/v3/advisories/GHSA-2qrg-x229-3v8q`](https://api.deps.dev/v3/advisories/GHSA-2qrg-x229-3v8q) #### Path parameters
  + advisoryKey.id: string
  + The OSV identifier for the security advisory.
  + advisoryKey: object
  + The identifier for the security advisory. Note that this may differ from the identifier in the request, due to canonicalization.
  + advisoryKey.id: string
  + The OSV identifier for the security advisory.
  + url: string
  + The URL of the security advisory.
  + title: string
  + A brief human-readable description.
  + aliases[]: string[]
  + Other identifiers used for the advisory, including CVEs.
  + cvss3Score: number
  + The severity of the advisory as a CVSS v3 score in the range [0,10]. A higher score represents greater severity.
  + cvss3Vector: string
  + The severity of the advisory as a CVSS v3 vector string.

  Query returns information about multiple package versions, which can be specified by name, content hash, or both. If a hash was specified in the request, it returns the artifacts that matched the hash.

  Querying by content hash is currently supported for npm, Cargo, Maven, NuGet, PyPI and RubyGems. It is typical for hash queries to return many results; hashes are matched against multiple release artifacts (such as JAR files) that comprise package versions, and any given artifact may appear in several package versions.

  Examples: - [`/v3/query?hash.type=SHA1&hash.value=ulXBPXrC%2FUTfnMgHRFVxmjPzdbk%3D`](https://api.deps.dev/v3/query?hash.type=SHA1&hash.value=ulXBPXrC%2FUTfnMgHRFVxmjPzdbk%3D) - [`/v3/query?versionKey.system=NPM&versionKey.name=react&versionKey.version=18.2.0`](https://api.deps.dev/v3/query?versionKey.system=NPM&versionKey.name=react&versionKey.version=18.2.0) #### Query parameters
  + hash.type: string
  + The function used to produce this hash.

    Can be one of

    ```
    MD5
    ```

    ,

    ```
    SHA1
    ```

    ,

    ```
    SHA256
    ```

    ,

    ```
    SHA512
    ```

    .
  + hash.value: string
  + A hash value.
  + versionKey.system: string
  + The package management system containing the package.

    Can be one of

    ```
    GO
    ```

    ,

    ```
    RUBYGEMS
    ```

    ,

    ```
    NPM
    ```

    ,

    ```
    CARGO
    ```

    ,

    ```
    MAVEN
    ```

    ,

    ```
    PYPI
    ```

    ,

    ```
    NUGET
    ```

    .
  + versionKey.name: string
  + The name of the package.
  + versionKey.version: string
  + The version of the package.
  + results[]: object[]
  + Results matching the query. At most 1000 results are returned.
  + results[].version: object
  + results[].version.versionKey: object
  + The name of the package version. Note that the package and version name may differ from names specified in requests, if applicable, due to canonicalization.
  + results[].version.versionKey.system: string
  + The package management system containing the package.

    Can be one of

    ```
    GO
    ```

    ,

    ```
    RUBYGEMS
    ```

    ,

    ```
    NPM
    ```

    ,

    ```
    CARGO
    ```

    ,

    ```
    MAVEN
    ```

    ,

    ```
    PYPI
    ```

    ,

    ```
    NUGET
    ```

    .
  + results[].version.versionKey.name: string
  + The name of the package.
  + results[].version.versionKey.version: string
  + The version of the package.
  + results[].version.publishedAt: string
  + The time when this package version was published, if available, as reported by the package management authority.
  + results[].version.isDefault: boolean
  + If true, this is the default version of the package: the version that is installed when no version is specified. The precise meaning of this is system-specific, but it is commonly the version with the greatest version number, ignoring pre-release versions.
  + results[].version.isDeprecated: boolean
  + If true, this version has been marked as deprecated.
  + results[].version.deprecatedReason: string
  + The reason why this version is deprecated.
  + results[].version.licenses[]: string[]
  + The licenses governing the use of this package version.

    We identify licenses as SPDX 2.1 expressions. When there is no associated SPDX identifier, we identify a license as “non-standard”. When we are unable to obtain license information, this field is empty. When more than one license is listed, their relationship is unspecified.

    For Cargo, Maven, npm, NuGet, PyPI, and RubyGems, license information is read from the package metadata. For Go, license information is determined using the licensecheck package.

    License information is not intended to be legal advice, and you should independently verify the license or terms of any software for your own needs.
  + results[].version.advisoryKeys[]: object[]
  + Security advisories known to affect this package version directly. Further information can be requested using the Advisory method.

    Note that this field does not include advisories that affect dependencies of this package version.
  + results[].version.advisoryKeys[].id: string
  + The OSV identifier for the security advisory.
  + results[].version.links[]: object[]
  + Links declared by or derived from package version metadata, to external web resources such as a homepage or source code repository. Note that these links are not verified for correctness.
  + results[].version.links[].label: string
  + A label describing the resource that the link points to.
  + results[].version.links[].url: string
  + The URL of the link.
  + results[].version.slsaProvenances[]: object[]
  + SLSA provenance information for this package version. Extracted from a SLSA provenance attestation. This is only populated for npm package versions. See the ‘attestations’ field for more attestations (including SLSA provenance) for all systems.
  + results[].version.slsaProvenances[].sourceRepository: string
  + The source code repository used to build the version.
  + results[].version.slsaProvenances[].commit: string
  + The commit of the source code repository the version was built from.
  + results[].version.slsaProvenances[].url: string
  + The URL of the provenance statement if there is one.
  + results[].version.slsaProvenances[].verified: boolean
  + The Sigstore bundle containing this attestation was verified using the sigstore-go library.
  + results[].version.attestations[]: object[]
  + Attestations for this package version.
  + results[].version.attestations[].type: string
  + The type of attestation. One of https://slsa.dev/provenance/v0.2, https://slsa.dev/provenance/v1, https://docs.pypi.org/attestations/publish/v1.
  + results[].version.attestations[].url: string
  + The URL of the attestation if there is one.
  + results[].version.attestations[].verified: boolean
  + The attestation has been cryptographically verified by deps.dev. For attestations distributed in a Sigstore bundle, this field indicates the bundle was verified using the sigstore-go library.
  + results[].version.attestations[].sourceRepository: string
  + Only set if type is https://slsa.dev/provenance/v0.2, https://slsa.dev/provenance/v1, https://docs.pypi.org/attestations/publish/v1. The source code repository used to build the version.
  + results[].version.attestations[].commit: string
  + The commit of the source code repository the version was built from.
  + results[].version.registries[]: string[]
  + URLs for the package management registries this package version is available from. Only set for systems that use a central repository for package distribution: Cargo, Maven, npm, NuGet, PyPI, and RubyGems.
  + results[].version.relatedProjects[]: object[]
  + Projects that are related to this package version.
  + results[].version.relatedProjects[].projectKey: object
  + The identifier for the project.
  + results[].version.relatedProjects[].projectKey.id: string
  + A project identifier of the form

    ```
    github.com/user/repo
    ```

    ,

    ```
    gitlab.com/user/repo
    ```

    , or

    ```
    bitbucket.org/user/repo
    ```

    .
  + results[].version.relatedProjects[].relationProvenance: string
  + How the mapping between project and package version was discovered.

    Can be one of

    ```
    SLSA_ATTESTATION
    ```

    ,

    ```
    GO_ORIGIN
    ```

    ,

    ```
    PYPI_PUBLISH_ATTESTATION
    ```

    ,

    ```
    RUBYGEMS_PUBLISH_ATTESTATION
    ```

    ,

    ```
    UNVERIFIED_METADATA
    ```

    .
  + results[].version.relatedProjects[].relationType: string
  + What the relationship between the project and the package version is.

    Can be one of

    ```
    SOURCE_REPO
    ```

    ,

    ```
    ISSUE_TRACKER
    ```

    .
  + results[].version.projectStatus: object
  + Whether a project is actively maintained, deprecated, etc. This field is not set for any package version outside of the PyPI system. See https://packaging.python.org/en/latest/specifications/project-status-markers/#project-status-markers for more information.
  + results[].version.projectStatus.status: string
  + results[].version.projectStatus.reason: string
