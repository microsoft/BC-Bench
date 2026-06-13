---
bc-version: [all]
domain: security
keywords: [nondebuggable, attribute, secrettext, unwrap, debugger]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Mark procedures that call SecretText.Unwrap() as [NonDebuggable]

## Description

`SecretText` transit — assignment, parameter passing, and return values — is auto-protected: the debugger sees a redacted placeholder, not the value. The protection ends the moment code calls `.Unwrap()`, which converts the `SecretText` back to plain `Text`. From that point on, the local variable holding the result is visible in the debugger like any other `Text`. The `[NonDebuggable]` attribute marks a procedure so that none of its locals or parameters are visible to the debugger during execution, which is exactly what is needed for any procedure that performs an `Unwrap()` or that otherwise materializes a secret as `Text` (for example, while parsing a JSON response to extract an access token).

## Best Practice

Apply `[NonDebuggable]` to any procedure whose body calls `.Unwrap()` on a `SecretText`, and to any procedure that constructs a `SecretText` from a `Text` source (such as a procedure that reads a JSON response body and converts the resulting `Text` into a `SecretText` for the caller). Keep the unwrap window as small as possible — ideally a single one-line helper that hands the unwrapped value straight to the consuming API. See sample: `nondebuggable-required-when-unwrapping-secrettext.good.al`.

## Anti Pattern

Calling `ApiKey.Unwrap()` inside a procedure that is not marked `[NonDebuggable]`. The unwrapped value is now an ordinary `Text` local and the debugger will display it, defeating the purpose of using `SecretText` in the first place. Reviewers should flag any `Unwrap()` call in a procedure that lacks the attribute, and any procedure that parses a credential out of a response (`access_token`, `id_token`, `client_secret`) without the attribute. See sample: `nondebuggable-required-when-unwrapping-secrettext.bad.al`.
