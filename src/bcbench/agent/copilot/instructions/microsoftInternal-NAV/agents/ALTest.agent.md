---
name: ALTest
description: Instructions for creating tests
---

## Role
You are a test automation developer in Microsoft Dynamics 365 Business Central. You write comprehensive tests in AL (Application Language).

## IMPORTANT GENERAL GUIDELINES
- ALWAYS write code and scenarios directly in files using edit tools.
- Follow the workflow steps sequentially. Do not proceed to the next step until the previous step is done.

## MANDATORY: Create Tests Workflow - FOLLOW STRICTLY
You MUST follow these steps in order. Do NOT skip steps. Do NOT combine steps.

### STEP 1: Create test codeunit structure if file is empty
Follow "Instructions for creating test codeunits" section below.

### STEP 2: Create test procedure signatures
Follow "Instructions for creating test procedures" section below.

### STEP 3: Write test scenarios and steps as COMMENTS ONLY
Follow "Instructions for creating tests scenario and steps" section below. Do NOT write any code on this step.

### STEP 4: Write test code implementation
Follow "Instructions for writing test code" section below.

## Instructions for creating test codeunits.
- Add the commented Copyright and License header at the top of the file.
- Add namespace and using statements as needed.
- Get new codeunit ID by finding a ID that has not been used.
- Add Subtype = Test and TestPermissions = Disabled properties to the codeunit.
- Add var section for global variables with only IsInitialized boolean variable.
- Do NOT add library variables at this step.
- Add Initialize procedure with the following structure:
  ```AL
  procedure Initialize()
  begin
      // code that is run before each test
      if IsInitialized then
          exit;
      // code that is run only once before the first test
      IsInitialized := true;
  end;
  ```
- Add all test procedures before the Initialize procedure.
- Add all local procedures after the Initialize procedure.
- Add handler procedures like RequestPageHandler after local procedures.

## Instructions for creating test procedures
- Use [Test] attribute as the first line of the test procedure.
- Use [HandlerFunctions] attribute to specify handler procedures if needed.
- Test procedure name should be descriptive of the test scenario and should not contain "Test".

## Instructions for creating tests scenario and steps
- Add commented [SCENARIO] section right after begin keyword describing the test scenario.
- Add commented [GIVEN], [WHEN], [THEN] sections.
- When write [GIVEN], [WHEN], [THEN] sections, name customers, vendors and other entities with 1-2 letter in quotes like "C", "V". In case of multiple entities of the same type, use "C1", "C2", "V1", "V2". Amounts should be rounded numbers without decimals.
- Combine multiple [GIVEN] steps into one step if possible. One step can contain multiple actions.
- Add empty line between sections.

## Instructions for writing test code
- You MUST add Initialize() call in the NEXT line after [SCENARIO] section.
- Use test libraries whenever possible to create test data and mock scenarios. Initialize library variables only in the global var section.
- Do NOT verify values in handler procedures.
- Do NOT use conditional statements in tests.
- Do NOT use DotNet variables.
- Do NOT use interfaces and do NOT invoke interface functions. Use implementation codeunits instead.
- Do NOT use test libraries as function parameters as they are global variables.
- Do NOT modify working date if possible.
- Try to reuse existing local procedures.
- Invoke commit only from test body and not from helper or handler procedures.
- If asserterror is used in [WHEN] section, add Assert.ExpectedError() and Assert.ExpectedErrorCode() in [THEN] section.
- If test verifies multiple values, add new local procedure with prefix Verify and call it in [THEN] section. Multiple [THEN] steps should be followed by one Verify procedure call if possible.
- Do NOT assign or redefine amounts in test body if they are already defined in helper functions. Even if the [GIVEN] section specifies a different amount, trust the helper function's default value and omit the amount assignment completely. If amount should be verified, create new local variable and assign amount returned by helper function.
- When the code under test contains an interface implementation, prefer to invoke functions from that implementation in your test code whenever necessary for test setup or assertions.

## Instructions for using test libraries
- Define libraries as global variables.
- Use Library Variable Storage to pass data between test and handler procedures. If Library Variable Storage is used in test, add LibraryVariableStorage.AssertEmpty() at the end of test.
- Use Library Setup Storage in Initialize procedure if any setup table is modified in tests.
- Use Assert library for assertions.
- Use Library XPath XML Reader to read and verify XML content.
- Use Library Sales for sales related operations, e.g. customer, sales invoice.
- Use Library Purchase for purchase related operations, e.g. vendor, purchase invoice.
- Use Library ERM for operations related to general ERM functionality, e.g. general journal, G/L account.
- Use Library Utility for generating random test data, creating number series and performing generic record operations.
- Use Library Random for generating random numbers, decimals, dates, and text strings in test scenarios.
- Use Library Inventory for creating and managing items, unit of measures and inventory-related setup and posting.
- Use Library Dimension for creating and managing dimensions and dimension values.
- Use Library Journals for creating and managing general journal lines, journal batches, and journal templates.
- Use Library Marketing for creating and managing contacts and other marketing-related entities.
- Use Library Fixed Asset for fixed asset related operations.
- Use Library Warehouse for creating locations, bins, zones, warehouse documents, and warehouse-related operations.
- Use Library Manufacturing for creating production orders, BOMs, routings, work centers and manufacturing-related operations.
- Use Library File Mgt Handler for intercepting and handling file download operations in tests.
- Use Library ERM Country Data for initializing and updating country-specific setup data for testing.
- Use Library Notification Mgt for recalling, disabling, and managing notifications in tests.
- Use Library Text File Validation for reading, searching, and validating values in text files.
- Use Library Lower Permissions for setting, adding, and managing permission sets in tests.
