---
bc-version: [all]
domain: security
keywords: [secretstrsubstno, secrettext, strsubstno, format, compose]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Use SecretStrSubstNo to compose strings that contain secrets

## Description

`SecretStrSubstNo` is the secret-preserving counterpart of `StrSubstNo`. It accepts a format string and arguments (any of which may be `SecretText`) and returns a `SecretText` — the substitution happens without ever materializing the result as plain `Text`. It is the right tool whenever a secret needs to be embedded in a larger string: an `Authorization: Bearer <token>` header value, a URI that includes an API key as a query parameter, or any other interpolation that combines a `SecretText` with surrounding context.

## Best Practice

Compose every secret-bearing string through `SecretStrSubstNo` and keep the result as `SecretText` end-to-end. Pass the result to the `SecretText` overload of the consumer — `HttpClient.SetSecretRequestUri`, `HttpHeaders.Add`, or `HttpContent.WriteFrom`. See sample: `secretstrsubstno-for-composing-secrets.good.al`.

## Anti Pattern

Calling `StrSubstNo('Bearer %1', Token.Unwrap())` to build the header value, or concatenating `'Bearer ' + Token.Unwrap()`. Both produce a plain `Text` containing the secret, which is then visible in the debugger and in any subsequent log or trace. Reviewers should flag any `Unwrap()` whose result is fed into `StrSubstNo` or used in `+` concatenation — `SecretStrSubstNo` removes the need for either. See sample: `secretstrsubstno-for-composing-secrets.bad.al`.
