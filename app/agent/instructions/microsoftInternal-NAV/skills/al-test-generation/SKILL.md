---
name: al-test-generation
description: Guide for creating AL tests for Microsoft Dynamics 365 Business Central. Use this when asked to write, create, or generate AL test codeunits, test procedures, or test automation for Business Central.
---

To create AL tests for Microsoft Dynamics 365 Business Central, follow this process:

## 1. Analyze the Code Under Test

Before writing any test code:
1. Read and understand the procedure or functionality being tested
2. Trace through all code paths to identify UI interactions
3. Examine table definitions for TableRelation constraints

## 2. Identify Required Handler Methods

**CRITICAL: Tests fail with "Unhandled UI" errors when handlers are missing.**

Look for these patterns in the code under test:

| Code Pattern                          | Required Handler            |
| ------------------------------------- | --------------------------- |
| `Confirm()`                           | `[ConfirmHandler]`          |
| `Message()`                           | `[MessageHandler]`          |
| `StrMenu()`                           | `[StrMenuHandler]`          |
| `Page.Run()`                          | `[PageHandler]`             |
| `Page.RunModal()`                     | `[ModalPageHandler]`        |
| `Report.Run()` or `Report.RunModal()` | `[ReportHandler]`           |
| Report request page                   | `[RequestPageHandler]`      |
| `Hyperlink()`                         | `[HyperlinkHandler]`        |
| `Notification.Send()`                 | `[SendNotificationHandler]` |

## 3. Analyze TableRelation Constraints

**CRITICAL: Tests fail with validation errors when inserting data that violates TableRelation constraints.**

Before inserting test data:
1. Read the table definition for all fields receiving values
2. Identify fields with `TableRelation` properties
3. Ensure related records exist before inserting test data
4. Use Library functions (e.g., `LibrarySales`, `LibraryPurchase`) to create prerequisite data

## 4. Write Test Structure

Follow the AAA pattern (Arrange-Act-Assert):

```AL
[Test]
[HandlerFunctions('RequiredHandlers')]
procedure TestProcedureName()
begin
    // [GIVEN] Setup test data and preconditions
    Initialize();
    CreateTestData();

    // [WHEN] Execute the action being tested
    ExecuteAction();

    // [THEN] Verify the expected results
    VerifyResults();
end;
```

## 5. Handler Method Signatures

```AL
[ConfirmHandler]
procedure ConfirmHandlerYes(Question: Text[1024]; var Reply: Boolean)
begin
    Reply := true;
end;

[MessageHandler]
procedure MessageHandler(Message: Text[1024])
begin
    // Empty - suppresses message display
end;

[ModalPageHandler]
procedure ModalPageHandler(var TestPage: TestPage "Page Name")
begin
    TestPage.OK().Invoke();
end;
```

## 6. Best Practices

- Use descriptive test procedure names that explain what is being tested
- One assertion concept per test
- Use Library Variable Storage to pass data between handlers and tests
- Do NOT verify values inside handler procedures
- Clean up test data in teardown or use transaction rollback
- Use `Initialize()` procedure to set up common test fixtures
