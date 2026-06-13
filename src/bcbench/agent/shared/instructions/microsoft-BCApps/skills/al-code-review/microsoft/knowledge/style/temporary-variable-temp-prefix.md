---
bc-version: [all]
domain: style
keywords: [temporary, temp, prefix, record-variable, naming]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Prefix temporary record variables with `Temp`

## Description

A `Record` variable declared with the `temporary` modifier behaves nothing like a normal record variable: it never touches the database, holds rows only for the lifetime of the variable, and is not visible to filters or queries on the underlying table. The BC convention is to make that difference visible at every call site by prefixing the variable name with `Temp` — `TempJobWIPBuffer`, `TempSalesLine`, `TempIntegerBuffer`. The convention is load-bearing for code review: when a reader sees `SalesLine.Insert()`, they expect a database write; when they see `TempSalesLine.Insert()`, they know it is an in-memory buffer.

## Best Practice

Every variable of type `Record X temporary` must start with `Temp`. The same applies to parameters: a procedure that receives a temporary record as a buffer names the parameter `TempBuffer`, `TempSalesLine`, and so on. The convention extends naturally to derived names — `TempJobWIPBufferCopy`, `TempSourceSalesLine` — anything that starts with `Temp` is in-memory.

See sample: `temporary-variable-temp-prefix.good.al`.

## Anti Pattern

`WIPBuffer: Record "Job WIP Buffer" temporary;` reads at the call site as if it were a database operation: `WIPBuffer.Insert()` looks identical to a write to the underlying table. The reader has to scroll back to the declaration to discover that this is in-memory, every time.

See sample: `temporary-variable-temp-prefix.bad.al`.
