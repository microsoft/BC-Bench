---
name: al-query-authoring
description: Guide for authoring Business Central AL query objects that answer data questions (joins, aggregates, filters, sorting). Use this when asked to write an AL query that returns Business Central data such as customers, vendors, items, sales, purchases, projects, or opportunities.
---

Write a single, compilable AL `query` object that returns exactly the data needed to answer
the question. Reference real Business Central tables and fields — a query that does not
compile, or returns the wrong data, fails.

## Structure

```al
query 50100 TopCustomersBySales
{
    QueryType = Normal;

    elements
    {
        dataitem(Customer; Customer)
        {
            column(No; "No.") { }
            column(Name; Name) { }
            dataitem(SalesLine; "Sales Line")
            {
                DataItemLink = "Sell-to Customer No." = Customer."No.";
                DataItemTableFilter = "Document Type" = const(Order);
                column(OutstandingAmount; "Outstanding Amount") { Method = Sum; }
            }
        }
    }
}
```

## Rules of thumb

- **Aggregate** a column with a method: `column(Total; "Amount (LCY)") { Method = Sum; }`
  (also `Average`, `Count`, `Min`, `Max`). Non-aggregated columns become the GROUP BY.
- **Join** by nesting a `dataitem` and linking it: `DataItemLink = "<child field>" = Parent."<field>";`.
- **Filter** rows with `DataItemTableFilter = "<field>" = const(<value>);` (e.g. an Option
  like `Document Type`) or a range/expression.
- **Order** with `OrderBy { descending(<column>); }` when the question asks for ranking or
  "top N" (combine with `TopNumberOfRows` where appropriate).
- **Quote** any field or table name that contains spaces or special characters: `"No."`,
  `"Sales Line"`, `"Amount (LCY)"`.
- Prefer stored fields; FlowFields and Option fields are supported.

## Common pitfalls

- Don't invent table or field names — use the real Business Central schema.
- Return only the columns the question needs; extra or missing columns change the result set.
- One `query` object per file.
