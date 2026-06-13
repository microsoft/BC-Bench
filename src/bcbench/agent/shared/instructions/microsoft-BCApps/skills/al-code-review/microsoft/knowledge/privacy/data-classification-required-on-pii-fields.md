---
bc-version: [all]
domain: privacy
keywords: [data-classification, pii, gdpr, customer-content, table-field, under-classified]
technologies: [al]
countries: [w1]
application-area: [all]
---

# DataClassification is required on table fields containing sensitive data

## Description

`DataClassification` is the AL property that tells the platform what kind of data a table field stores so that telemetry, GDPR data-subject requests, and the platform's audit surfaces can treat it correctly. It is required on any field that holds personal or customer data. The default value `SystemMetadata` means "no user or customer data" — applying it to a field that actually holds PII (an email address, a customer name, an employee code) is an under-classification and a privacy bug, even though the code still compiles.

## Best Practice

Set `DataClassification` to the value that matches the data the field actually stores. A `Customer."E-Mail"`-style field is `CustomerContent` (data belonging to the tenant's customers); a personal identifier such as an employee number or user ID is `EndUserIdentifiableInformation` or `EndUserPseudonymousIdentifiers` depending on whether it is directly identifying. Choose the classification at field definition time — fixing it later is a schema change.

See sample: `data-classification-required-on-pii-fields.good.al`.

## Anti Pattern

Declaring a field that stores PII with `DataClassification = SystemMetadata` to silence the compiler warning. The field compiles but the platform now treats customer data as system metadata in telemetry, GDPR exports and admin reports.

See sample: `data-classification-required-on-pii-fields.bad.al`.
