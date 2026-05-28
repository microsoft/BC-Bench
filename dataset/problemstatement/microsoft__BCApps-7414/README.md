# [Shopify] Sync HS Code and Country of Origin on variant export

## Summary

Addresses gaps identified in the Shopify Agentic Plan Product Sync Guide to ensure BC product catalogs meet the data requirements for AI channel distribution.

- **Harmonized System Code**: Sync `Item."Tariff No."` as `harmonizedSystemCode` on variant export (both create and update paths)
- **Country of Origin**: Sync `Item."Country/Region of Origin Code"` as `countryCodeOfOrigin` on variant export
- New fields added to `Shpfy Variant` table and populated in `CreateTempProduct` (4 code paths) and `FillInProductVariantData` (3 overloads)
- New `Sync HS Code and Country of Origin` boolean on the Shop card (default on) gates the variant-field population, matching the pattern used by `Sync Item Extended Text` / `Marketing Text` / `Attributes`
- Tests added for HS code and country of origin field population

Related docs PR for External URL extensibility example: MicrosoftDocs/dynamics365smb-devitpro#7259

Fixes [AB#632223](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/632223)




