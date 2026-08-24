---
name: bc-al-query-mcp
description: "Use when: writing, fixing, validating, or running Business Central AL query objects with bc_data MCP tools and Microsoft Learn MCP docs. Covers AL query syntax, table discovery, schemas, relations, joins, filters, FlowFields, pagination, and read-only data retrieval."
argument-hint: "[business question, data need, or AL query to fix]"
user-invocable: true
disable-model-invocation: false
---

# Business Central AL Query MCP

Use this skill when the user asks to query Business Central data, write or fix an AL `query` object, join BC tables, discover BC fields, validate an AL query, or use the `bc_data` MCP tools together with Microsoft Learn.

## Required Capabilities

The environment should expose these MCP tool groups:

- Microsoft Learn MCP: docs search, docs fetch, and code sample search for official AL query syntax and examples.
- Business Central data MCP: table search, table schema, table relations, and AL query compile/run.

If tools are deferred, load them with tool search before use. Do not assume a tool is available until it has been loaded or returned by discovery.

The MCP tool names may appear with a server-name prefix that differs by host — for example `bcmcp-bc_data_query` (Copilot CLI) or `mcp__bcmcp__bc_data_query` (Claude Code). The bare names used below (`bc_data_find_tables`, `bc_data_get_table_schema`, `bc_data_get_table_relations`, `bc_data_query`) refer to these tools regardless of prefix; always invoke the exact name shown in your available tool list or returned by tool search.

## Core Rule

Microsoft Learn provides general AL query authoring knowledge. The BC data MCP tools provide live tenant-specific metadata and execution. Use both. Never write a tenant query from memory alone.

## Non-Negotiables

- Always use `bc_data_get_table_schema` for every table before writing the query.
- Always verify joins with `bc_data_get_table_relations` before writing a multi-table query.
- Prefer `bc_data_find_tables` with `searchMode: keyword` for known BC entity names. Use semantic search only as a supplement and verify results.
- Compile with `bc_data_query` and `returnData: false` before running with `returnData: true`.
- Keep queries read-only, narrow, and paged. Use only the columns needed for the user's question.
- Do not dump sensitive raw business data unless the user explicitly asks for rows. Prefer summaries, counts, and representative samples.
- If a compile or execution error occurs, use the diagnostic location plus schema/relations to repair the same query. Do not blindly rewrite from scratch.
- If permissions, missing tables, or unavailable MCP tools block the task, report the exact blocker and the next viable option.

## Workflow

1. Identify the user's actual data question.
   - Determine the business entity, date range, filters, measures, and whether raw rows or an aggregate answer is needed.
   - Ask a concise clarification only if the query cannot be scoped safely.

2. Ground AL syntax in Microsoft Learn when needed.
   - Search/fetch docs for `Business Central AL query object`, `DataItemLink`, `SqlJoinType`, `DataItemTableFilter`, `ColumnFilter`, `Filtering in Query objects`, and `Aggregating data in Query objects`.
   - Use code sample search with `language: al` when examples are useful.

3. Discover the live tables.
   - Use keyword search for likely names, for example `customer`, `sales invoice`, `item ledger entry`, `vendor ledger entry`.
   - If the user describes a business concept instead of table names, try semantic search, but validate with keyword search and schemas.

4. Inspect schemas.
   - Call schema for every candidate table.
   - Use `nameContains` to narrow large schemas, for example `['no', 'posting date', 'amount', 'customer']`.
   - Note primary keys, field names, field classes, field types, FlowFields, FlowFilters, and relation hints.

5. Discover joins.
   - For each multi-table query, call relations in the useful direction.
   - Use `relatedToTableIds` when checking a specific join path.
   - Remember that `DataItemLink` is set on the lower/nested dataitem.

6. Compose the AL query.
   - Use a normal query object unless the user specifically needs an API query.
   - Quote table and field names that contain spaces, punctuation, or reserved words.
   - Use stable column aliases without spaces, usually underscores.
   - Put parent tables higher and child/detail tables nested beneath them.
   - Set `SqlJoinType = InnerJoin;` when only matching child rows should appear. If omitted, AL query dataitems default to `LeftOuterJoin`.
   - Use `DataItemTableFilter` for static filters.
   - For date filters in the BC data MCP execution path, prefer quoted ISO date strings, for example `filter('2025-01-01'..'2025-01-31')`.
   - Use FlowFields only when needed; they can be convenient but may add subqueries and cost.

7. Validate before execution.
   - First call `bc_data_query` with `returnData: false`.
   - Confirm the returned columns, types, and dataitems match the intended shape.
   - If validation fails, fix field names, aliases, links, filter syntax, or query structure using the exact diagnostic.

8. Run safely.
   - Use `returnData: true`, `top` no larger than needed, and `skip` for paging.
   - Use `resultFormat: resource` for larger results or when downstream analysis is needed.
   - On page 0, use `totalCount` when present. Continue paging only when the user needs more data.

9. Present the result.
   - Include the final AL query when the user asked for a query or when it helps reproducibility.
   - State which tables, fields, joins, and filters were used.
   - Summarize results without overexposing tenant data.
   - Mention validation status: compiled only, compiled and ran, or blocked with reason.

## Query Patterns

### Single Table

```al
query 50100 CustomerOverview
{
    QueryType = Normal;

    elements
    {
        dataitem(Customer; Customer)
        {
            column(No_; "No.") { }
            column(Name; Name) { }
            column(Blocked; Blocked) { }
            column(Balance_LCY; "Balance (LCY)") { }
        }
    }
}
```

### Header And Lines

```al
query 50101 PostedSalesInvoiceLines
{
    QueryType = Normal;

    elements
    {
        dataitem(SalesInvoiceHeader; "Sales Invoice Header")
        {
            column(Invoice_No_; "No.") { }
            column(Sell_to_Customer_No_; "Sell-to Customer No.") { }
            column(Posting_Date; "Posting Date") { }

            dataitem(SalesInvoiceLine; "Sales Invoice Line")
            {
                DataItemLink = "Document No." = SalesInvoiceHeader."No.";
                SqlJoinType = InnerJoin;

                column(Line_No_; "Line No.") { }
                column(Item_No_; "No.") { }
                column(Description; Description) { }
                column(Quantity; Quantity) { }
                column(Line_Amount; Amount) { }
            }
        }
    }
}
```

### Static Date Filter

```al
DataItemTableFilter = "Posting Date" = filter('2025-01-01'..'2025-01-31');
```

### Aggregate Column

```al
column(Total_Quantity; Quantity)
{
    Method = Sum;
}
```

## Common Recovery Moves

- `AL0345` or invalid column source: re-check schema for the exact field name on the parent dataitem's table.
- Join returns too many rows: verify `DataItemLink` field direction and add `SqlJoinType = InnerJoin;` when appropriate.
- No rows returned: validate filters first, then run a smaller unfiltered query with identifying columns.
- Date filter errors: use quoted ISO date strings in the filter expression.
- Semantic table search returns nothing: retry with keyword fragments and inspect schemas.
- Large result sets: reduce columns, add filters, page with `top`/`skip`, or use `resultFormat: resource`.

## Quality Bar

A good answer from this skill includes enough evidence that the query is grounded in the live environment: discovered tables, checked fields, verified relations, compile status, and a safe execution or clear blocker. The agent should not merely produce plausible AL code; it should validate the query against the connected Business Central instance whenever the tools are available.
