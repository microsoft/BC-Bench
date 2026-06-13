---
bc-version: [all]
domain: style
keywords: [object-name, length, prefix, affix, 30-characters, appsource]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Keep object names within the 30-character platform limit

## Description

Business Central object names — for tables, pages, codeunits, reports, queries, XML ports, enums, and permission sets — are limited to 30 characters in total. AppSource and per-tenant extensions also have to carry a mandatory prefix or affix (typically 3–4 characters), which leaves roughly 26 characters for the descriptive part of the name. Names hitting the 30-character ceiling are routinely rejected at publish time, and over-aggressive abbreviation to fit (`CustLE`, `SIPoster`, `SalesInv`) makes the object name opaque to reviewers and to anyone reading dependency lists. The right move is to plan name length around the budget — descriptive base + prefix — not to discover the limit during AppSource validation.

## Best Practice

Choose a clear, descriptive name in the 20–26-character range and reserve the remaining characters for the mandatory app prefix. `"Customer Ledger Entry"`, `"Sales Invoice Posting"`, `"Sales Invoice"` are descriptive and well under the budget. When you genuinely need to abbreviate, prefer abbreviations that are already established in BC (`Cust.`, `Vend.`, `Gen. Jnl.`, `WHSE`) over ad-hoc shortenings.

## Anti Pattern

Names like `"CustLE"` or `"SIPoster"` that abbreviate beyond comprehensibility, or names like `"Customer Ledger Entry Posting Helper Codeunit"` that breach 30 characters and force a rename during publish.
