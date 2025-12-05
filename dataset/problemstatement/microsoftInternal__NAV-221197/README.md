Title: Error in report 6520 "Item Tracing Specification" when Item Description field is over 50 characters
Repro Steps:
Steps to recreate:
1. Create an item and set it up to be traceable via item tracking (I used lot tracking), or use an existing item with tracking enabled
2. Modify the Description of the item to be longer than 50 characters
3. Create and post any traceable transaction
4. Navigate to page 6520 "Item Tracing" and trace the lot/serial/package number
5. Select "Print" and under "Column Selection" input 25 or use the lookup function to select the "Item Description" field
6. Preview the report

Trace of error 
"env_time": 2025-06-26T08:49:34.0311980Z,
"Business Hours": Within (UK South),
"category": ExecuteALFunction,
"severity": 2,
"message": ExecuteALFunction Failed: Page 6520 Page 6520 - Item Tracing

Description:

