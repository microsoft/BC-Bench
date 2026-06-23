---
bc-version: [all]
domain: style
keywords: [file-name, object-type, suffix, naming-convention]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Name AL source files `<ObjectName>.<ObjectType>.al`

## Description

Each AL source file holds a single object, and the file name is expected to be of the form `<ObjectName>.<ObjectType>.al` — `CustomerCard.Page.al`, `PostSalesInvoice.Codeunit.al`, `NoSeriesTests.Codeunit.al`, `SalesHeader.TableExt.al`. The pattern makes object types greppable from a file listing and lets tooling — symbol search, project explorers, code generators — locate objects without parsing the AL source. Snake-case, lowercase-only, or type-less file names (`customer_page.al`, `tests_noSeries.al`, `PostSalesInvoiceLogic.al`) all break that contract.

## Best Practice

Use PascalCase for the object portion, no spaces, no underscores; the type segment is one of the AL object-type names — `Page`, `Codeunit`, `Table`, `TableExt`, `Report`, `Query`, `XmlPort`, `Enum`, `EnumExt`, `Interface`, `PermissionSet`, `PageExt`, `ReportExt`. The object portion should echo the object's name as it appears in AL.

See sample (file-naming pattern is structural; no AL sample shipped here).

## Anti Pattern

`customer_page.al`, `PostSalesInvoiceLogic.al`, `tests_noSeries.al`. The first uses snake_case and lower-case; the second omits the type segment entirely; the third inverts the order and uses mixed casing. All three break grep, symbol search, and the implicit map between file system and AL object table.
