---
bc-version: [all]
domain: style
keywords: [page-name, source-table, misleading, naming]
technologies: [al]
countries: [w1]
application-area: [all]
---

# A page or view name must describe the table it shows

## Description

A page (or filtered page View) whose name references one entity but whose `SourceTable` is a different entity misleads every consumer of the object's metadata. A page named `"Items with Negative Inventory"` that sources `"Stockkeeping Unit"` looks like a list of items in the search bar and in role explorer, but presents stockkeeping-unit fields and behaviour. The fix is either to rename the page to match the source table — `"Stockkeeping Units with Negative Inventory"` — or to change the source table to the entity the name promises. The choice depends on which the actual users are asking for; the constraint is that the two MUST agree.

The rule extends to filtered Views declared inside a page: the `View` name should describe the filter applied to the page's existing source, not introduce a different entity.

## Best Practice

Read the page name out loud and ask: "If a user typed this into the search bar, would they expect to see rows from `<SourceTable>`?" If the answer is no, rename one side or the other. The same check applies whenever the source table changes — the name has to follow.

## Anti Pattern

`page "Items with Negative Inventory" { SourceTable = "Stockkeeping Unit"; … }`. The Tell-Don't-Ask name asserts items; the source contradicts it. Reviewers should flag every mismatch they spot, even when both sides "make sense individually" — they have to agree.
