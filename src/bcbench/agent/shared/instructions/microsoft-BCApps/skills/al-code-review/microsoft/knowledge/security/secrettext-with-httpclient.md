---
bc-version: [all]
domain: security
keywords: [secrettext, httpclient, setsecretrequesturi, containssecret, headers, http]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Use the SecretText-aware HttpClient surface for secrets in requests

## Description

`HttpClient` and its companion types expose a parallel surface that accepts `SecretText` instead of `Text`, so that secret URIs, secret headers, and secret request bodies never round-trip through plain text. The key entry points are: `HttpClient.SetSecretRequestUri()` for URIs that contain secrets (the subsequent `Get`/`Post` is then called with an empty string); `HttpHeaders.Add()` overload that accepts a `SecretText` value for authorization headers; `HttpHeaders.ContainsSecret()` to test whether a secret header is present (the plain `Contains()` returns false for secret headers); `HttpContent.WriteFrom()` and `HttpContent.ReadAs()` overloads that accept and produce `SecretText` for request and response bodies that carry credentials.

## Best Practice

When the URI contains a secret query parameter, compose it as `SecretText` (see `secretstrsubstno-for-composing-secrets.md`), pass it to `SetSecretRequestUri`, and call `Get('', Response)` with an empty string as the URI argument. When the credential is an authorization header, build the header value as `SecretText` and pass it to `Headers.Add`. Use `ContainsSecret` rather than `Contains` to check for the presence of a secret header. See sample: `secrettext-with-httpclient.good.al`.

## Anti Pattern

Calling `ApiKey.Unwrap()` to build a URI or header string and passing the resulting `Text` to `HttpClient.Get` or `Headers.Add`. The unwrapped secret is now visible in the debugger, in any HTTP trace that captures the request URI, and in any error that includes the URI. Reviewers should flag any `Unwrap()` call whose result flows into an `HttpClient` argument; the `SecretText` overload exists precisely so the unwrap is not needed. See sample: `secrettext-with-httpclient.bad.al`.
