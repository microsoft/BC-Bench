Title: "Journal Template Name must have a value" error message appears if you try to Calculate and Post VAT Settlement and Journal Template Name Mandatory is enabled in the G/L Setup.
Repro Steps:
1.Go to G/L Setup.
2.Settings -> Design -> Add Journal Template Name Mandatory and enable it.
3.Search for Calculate and Post Vat Settlement.
4.Add any dates for:
  a. Ending Date
  b. Posting Date.
  c. Add Settlement Account.
  d. Enable Post.
5.After Preview, the following error occurs " Journal Template Name must have a value in Gen. Journal Line: Journal Template Name=, Journal Batch Name=, Line No.=0. It cannot be zero or empty."
6.If you disable the Journal Template Name Mandatory, It works fine.

We guess a kind of control should be set in this scenario, so this check is not executed.
If there is anything we are missing, please let us know what.
Thanks!

Description:
"Journal Template Name must have a value" error message appears if you try to Calculate and Post VAT Settlement and Journal Template Name Mandatory is enabled in the G/L Setup.
