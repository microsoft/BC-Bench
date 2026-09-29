# Repeated deletion of a retrospective service invoice does not reset invoiced dates

## Description

A previous correction to retrospective service invoicing, tracked as Bug 640080, fixed the period start date and allowed **Invoiced to Date** to be restored when an unposted invoice was deleted for the first time.

An issue remains when the invoice is created and deleted again. After deleting the second unposted service invoice, newly added service items keep **Invoiced to Date = 31 March 2026** instead of resetting. This prevents the next service invoice from being created with the correct retrospective periods.

## Steps to reproduce

1. In a Switzerland (CH)-localized CRONUS company, set **User Experience** to **Premium** in **Company Information**.
2. Prepare service contract template `TEMPL0002` as a prepaid contract invoiced quarterly.
3. Create three service items for customer `10000`, each using item `S-100`. Refer to them as items A, B, and C.
4. Set the work date to `1 January 2026`.
5. Create a prepaid quarterly service contract for customer `10000` from template `TEMPL0002`, add item A, and run **Sign Contract**.
6. Run **Create Service Invoice**, open the invoice, and post the initial first-quarter invoice for item A.
7. Add **Invoiced to Date** to the Service Contract Lines part through personalization or profile configuration.
8. Set the work date to `1 February 2026`, open the contract, and add item B with a starting date of `1 February 2026`.
9. Lock the contract. Process the new line, but decline creation of the retrospective invoice.
10. Set the work date to `1 March 2026`, reopen the contract, and add item C with a starting date of `1 March 2026`.
11. Lock the contract again. Process the new line, but decline invoice creation.
12. Set the work date to `1 April 2026` and run **Create Service Invoice**. Create the retrospective invoice for February and March.
13. Delete the unposted service invoice and restore the previous invoice dates.
14. Run **Create Service Invoice** again to recreate the retrospective invoice.
15. Delete the second unposted service invoice and restore the previous invoice dates again.
16. Reopen the service contract and inspect **Invoiced to Date** on lines A, B, and C.

## Expected behavior

- Item A retains **Invoiced to Date = 31 March 2026** because its first-quarter invoice was posted.
- Items B and C reset to a blank date because both retrospective invoices were deleted.
- A subsequent service invoice can be created with the correct retrospective periods.

## Actual behavior

After the second unposted invoice is deleted, items B and C remain at **Invoiced to Date = 31 March 2026**, preventing the next service invoice from being created correctly.
