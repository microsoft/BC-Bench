# Render per-row Currency Code in Aged Accounts Receivable/Payable Excel

## Summary

The `CurrencyCode` column in Aged Accounts Receivable Excel (report 4402) and Aged Accounts Payable Excel (report 4403) was bound to a single AgingData-buffer-wide variable (`CurrencyCodeDisplayCode`) computed once after `InsertAgingData`. Every row of a given customer/vendor displayed the same currency — the last one inserted into the buffer. Customers/vendors with entries in multiple currencies saw foreign-currency rows mislabeled with the LCY code (or vice versa).

This change:
- Binds the `CurrencyCode` column directly to `AgingData."Currency Code"` so each row renders its own currency.
- Falls back to G/L Setup's LCY Code at insertion time when the ledger entry's `Currency Code` is empty.
- Splits the Aged Accounts tests out of `TrialBalanceExcelReports.Codeunit.al` into a new dedicated `AgedAccountsExcelReports.Codeunit.al` (139547), and adds per-row currency rendering tests for both reports.

Fixes [AB#637444](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/637444)

## Test plan
- [x] New tests `AgedAccountsRecRendersCurrencyCodePerEntry` and `AgedAccountsPayableRendersCurrencyCodePerEntry` cover the multi-currency rendering case
- [x] Existing Aged Accounts tests continue to pass after relocation








