---
bc-version: [all]
domain: privacy
keywords: [in-memory, dictionary, list, temporary-table, variable, memory-dump]
technologies: [al]
countries: [w1]
application-area: [all]
---

# In-memory variables, dictionaries, lists and temporary tables are not a privacy concern

## Description

AL runs in a managed server environment. Local variables, `Dictionary`, `List`, temporary `Record` variables, and other in-process data structures exist only for the duration of the request or session and are released by the runtime when it ends — they are not persisted, not visible across sessions, and not exposed outside the server process. Memory dumps are not a realistic threat vector against Business Central's hosted architecture, so holding business data (emails, names, addresses, document content) in these structures while processing a request is normal and expected.

## Best Practice

Use whatever in-memory shape (`Dictionary`, `List`, temporary tables, plain variables) the algorithm needs. The privacy review applies to *persistent* surfaces — table fields, telemetry, outgoing HTTP — not to per-request memory.

## Anti Pattern

Flagging a `Dictionary of [Text, Text]` populated with customer emails, or a temporary `Record Customer` holding rows mid-processing, as a privacy leak. These structures are scoped to the request and do not leave the server's memory.
