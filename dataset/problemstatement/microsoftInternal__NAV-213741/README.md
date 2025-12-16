# Title: Missing handling of "Direct Cost - Non Inventory" cost type for assemblies in "Inventory Posting to G/L" codeunit.
## Repro Steps:
The codeunit "Inventory Posting To G/L" has a handler for the new "Direct Cost - Non Inventory" cost type in BufferOutputPosting function, but doesn't have the handler in BufferAsmOutputPosting function.

**Call stack a partner has reported:**
Inventory Posting To G/L(CodeUnit 5802).BufferAsmOutputPosting line 70 - Base Application by Microsoft
Inventory Posting To G/L(CodeUnit 5802).BufferInvtPosting line 62 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).PostInvtBuffer line 2 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).PostValueEntryToGL line 4 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).PostInventoryToGL line 22 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).InsertValueEntry line 82 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).ItemValuePosting line 28 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).CheckRunItemValuePosting line 12 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).PostItem line 83 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).Code line 137 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).PostSplitJnlLine line 12 - Base Application by Microsoft
Item Jnl.-Post Line(CodeUnit 22).RunWithCheck line 16 - Base Application by Microsoft
Inventory Adjustment(CodeUnit 5895).PostItemJnlLine line 57 - Base Application by Microsoft
Inventory Adjustment(CodeUnit 5895).PostOutput line 30 - Base Application by Microsoft
Inventory Adjustment(CodeUnit 5895).PostOutputAdjmtBuf line 5 - Base Application by Microsoft
Inventory Adjustment(CodeUnit 5895).MakeAssemblyAdjmt line 18 - Base Application by Microsoft
Inventory Adjustment(CodeUnit 5895).MakeMultiLevelAdjmt line 22 - Base Application by Microsoft
Inventory Adjustment(CodeUnit 5895).MakeMultiLevelAdjmt line 15 - Base Application by Microsoft
Inventory Adjustment Handler(CodeUnit 5894).MakeInventoryAdjustment line 16 - Base Application by Microsoft
Cost Adjustment Item Runner(CodeUnit 5823).OnRun(Trigger) line 8 - Base Application by Microsoft
Adjust Cost - Item Entries(Report 795).RunCostAdjus

**Repro steps from a partner:**
I was doing some testing, and when i run the cost adjustment report it showed this error.
The following combination Item Ledger Entry Type = Assembly Output, Entry Type = Direct Cost - Non Inventory, and Expected Cost = No is not allowed.
But i do not have this combination on value entries.
Check image "Value entries" I am not quite sure why is showing this message.
Error message: The following combination Item Ledger Entry Type = Assembly Output, Entry Type = Direct Cost - Non Inventory, and Expected Cost = No is not allowed.
AL call stack: "Adjust Cost - Item Entries"(Report 795).RunCostAdjustmentWithLogging line 22 - Base Application by Microsoft
" Adjust Cost - Item Entries"(Report 795).OnPreReport(Trigger) line 19 - Base Application by Microsoft
Thank you.
Best regard
## Description:
