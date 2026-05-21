# Table Relations

**CRITICAL: Analyze `TableRelation` properties before inserting test data.**
Tests fail with validation errors when inserted data violates a `TableRelation`.

## Why It Matters

The `TableRelation` property establishes lookups into other tables and validates entries. When a field has a `TableRelation`, the value assigned MUST exist in the related table and satisfy any filter conditions.

## Analysis Procedure (BEFORE inserting test data)

1. Read the table definition for all fields that will receive values.
2. For each field with a `TableRelation` property, identify:
   - The related table and field (e.g., `TableRelation = Customer."No."`)
   - Any `WHERE` filter conditions (e.g., `WHERE("Balance (LCY)" = FILTER(>= 10000))`)
   - Any conditional relations using `IF` (e.g., `IF (Type = CONST(Customer)) Customer ELSE IF (Type = CONST(Item)) Item`)
3. Ensure related records exist before assigning values to fields with `TableRelation`.
4. Ensure related records satisfy any `WHERE` filter conditions.
5. For conditional relations, set the condition field BEFORE assigning the relation field.

## TableRelation Syntax Forms

- **Simple**: `TableRelation = <TableName>[.<FieldName>]`
- **Filtered**: `TableRelation = <TableName> WHERE(<Field> = CONST(<Value>))`
- **Conditional**: `TableRelation = IF (<Condition>) <TableName> ELSE <AnotherTable>`
- **Field-based filter**: `TableRelation = <TableName> WHERE(<Field> = FIELD(<SourceField>))`

## Rules

- **ALWAYS** read the field definition to check for `TableRelation` before assigning values.
- **ALWAYS** ensure the related record exists in the referenced table before assignment.
- **ALWAYS** set condition fields (used in `IF` clauses) BEFORE setting the relation field.
- **ALWAYS** verify that related records satisfy any `WHERE` filter conditions.
- **PREFER** Library codeunits (`LibrarySales`, `LibraryPurchase`, `LibraryInventory`, …) — they handle table relations automatically.
- **NEVER** assign arbitrary values to fields with `TableRelation` without verifying the related record exists.

## Examples

```AL
// BAD: Inserting data without checking TableRelation - will fail validation
SalesLine."Sell-to Customer No." := 'INVALID-CUSTOMER';  // Customer may not exist!
SalesLine.Insert();

// GOOD: Create or find related record first, then assign
Customer.Init();
Customer."No." := LibraryUtility.GenerateGUID();
Customer.Insert(true);
SalesLine."Sell-to Customer No." := Customer."No.";
SalesLine.Insert();

// GOOD: Use library functions that handle relations automatically
LibrarySales.CreateCustomer(Customer);
LibrarySales.CreateSalesLine(SalesLine, SalesHeader, SalesLine.Type::Item, ItemNo, Quantity);
```

```AL
// Conditional TableRelation: IF (Type = CONST(Customer)) Customer ELSE IF (Type = CONST(Item)) Item

// BAD: Setting relation field before condition field
MyRecord.Relation := Customer."No.";  // Type not set yet — validation uses wrong table!
MyRecord.Type := TypeEnum::Customer;

// GOOD: Set condition field FIRST, then relation field
MyRecord.Type := TypeEnum::Customer;
MyRecord.Relation := Customer."No.";
```

```AL
// Filtered TableRelation: TableRelation = Vendor WHERE("Balance (LCY)" = FILTER(>= 10000))

// BAD: Using a vendor that doesn't meet the filter criteria
Vendor."Balance (LCY)" := 5000;
MyRecord."Vendor No." := Vendor."No.";  // Validation may fail!

// GOOD: Ensure the related record meets the filter conditions
Vendor."Balance (LCY)" := 15000;
Vendor.Modify();
MyRecord."Vendor No." := Vendor."No.";
```
