---
bc-version: [all]
domain: security
keywords: [isolatedstorage, setencrypted, encryption, secret, storage]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Prefer IsolatedStorage.SetEncrypted over Set for sensitive values

## Description

`IsolatedStorage` exposes two write entry points: `Set` stores the value as-is, and `SetEncrypted` stores it encrypted at rest. Both are scoped per extension, but only `SetEncrypted` adds the additional protection that the value is not readable from the underlying storage by anything that bypasses the AL `IsolatedStorage` API. The choice between them is by intent: configuration that is not sensitive (a user preference, a default flag) can use `Set`; anything that would harm the tenant if leaked — API keys, tokens, connection strings, OAuth client secrets — uses `SetEncrypted`.

## Best Practice

Use `IsolatedStorage.SetEncrypted` for every value that meets the definition of a secret. Pair it with the matching retrieval pattern: `IsolatedStorage.Contains` to test for presence and `IsolatedStorage.Get` (preferably with a `SecretText` destination) to read. Constrain the input length before storing — long values can exceed the encrypted-storage size limit and the write will fail at runtime. See sample: `isolatedstorage-setencrypted-for-sensitive-values.good.al`.

## Anti Pattern

`IsolatedStorage.Set('ApiKey', ApiKeyValue, DataScope::Module)` — the key is now sitting in storage unencrypted, and any future incident that exposes the underlying storage exposes the key. Reviewers should flag any `IsolatedStorage.Set` whose key name or surrounding context suggests a secret (`ApiKey`, `Token`, `Password`, `Secret`, `ClientSecret`). See sample: `isolatedstorage-setencrypted-for-sensitive-values.bad.al`.
