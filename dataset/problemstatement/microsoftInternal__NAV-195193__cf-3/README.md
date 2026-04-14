# Title: Excel layouts - dim breakdown results in repeated values (Trial Balance report a.o.)
## Repro Steps:
Open the Trial Balance Excel report
run it for p1..p3
tip: in US you can run it with this acc. filter:
![Filter](./filter.png)
so buggy rows are in top of page  ;o)
open excel
open TrialBalanceData tab

**expected**: debit/credit reflects latest validation (no explicit reset required)

**actual**: repeated values for dimensions   (NetchangeDebit and Balance Debit)
![Excel Table](./excel_table.png)
the repeated rows/fields appears to just 'sit' in the reports - because the other numbers are correct:
![LCY](./LCY.png)
 compared to a financial reported filtered for same dim:
![Finance Report](./finance_report.png)

## Description:
