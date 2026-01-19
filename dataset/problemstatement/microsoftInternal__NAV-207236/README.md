# Title: Post Batch of Sales Invoices with Currency Code and Replace Posting Date does not longer work
## Repro Steps:
1 Create a new sales invoice 
![Sales Invoice Step1](./sales_invoice_step1.png)
2.Select the currency code to USD
![Invoice Details Step2](./invoice_details_step2.png)
3.Add a single new line with item "1896-S" and quantity = 1
![Lines Step3](./lines_step3.png)
4.Go back to the overview of "Sales Invoices" and select the action "Post Batch..." when selecting your newly created "Sales Invoice"
select in the request page a different "Posting Date" like 1st January 2025
Select "Replace Posting Date" and "Replace Document Date"
![Information Step4](./information_step4.png)
![Sales Invoice Step4](./sales_invoice_step4.png)
![Batch Post Sales Invoice Step4](./batch_post_sales_invoice_step4.png)
5.Then when processing the invoice you receive this message:
![Message Step5](./message_step5.png)
If you select "No" then an error occurs, If you select "Yes" all lines will be recreated and all changes on the prices, amounts, discounts or description are lost on the lines because the lines get these information's from the base data. This is critical because not all lines get always their prices from a price list.
![Changes Step5](./changes_step5.png)
So the action "Batch Post..."  or the report 297 "Batch Post Sales Invoices" are not usable for our customer.
Following my further investigation, I made an attempt to replicate this issue on 24.5 and 25.0 versions it was working as expected.
![102228 Invoice Step5](./102228_invoice_step5.png)
![Invoice Details Step5](./invoice_details_step5.png)

And also following cx statement after checking through base code:
The critical change was made in the table "Sales Header". There a new procedure was added called "BatchConfirmUpdatePostingDate". In here the field "Currency Code" is validated. If you debug the process you will see in a further step the "Currency Code" gets checked if it is different than before. This does not work because during the process in this case the xRec in the Validate-trigger is not initialized and the check will always result in an true which leads to the nice message which leads to our problem.

Issue: Post Batch of Sales Invoices with Currency Code and Replace Posting Date does not longer work

Expected result: It is expected that all lines should maintain the same amount as it was when creating the sales invoice

## Description:
Issue: Post Batch of Sales Invoices with Currency Code and Replace Posting Date does not longer work

Expected result: It is expected that all lines should maintain the same amount as it was when creating the sales invoice
