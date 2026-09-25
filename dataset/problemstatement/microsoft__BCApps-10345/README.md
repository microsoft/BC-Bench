# Deleting a recreated retrospective service invoice does not reset invoiced dates

## Reproduction steps

1. In a Switzerland (CH)-localized CRONUS company, open **Company Information** and set **User Experience** to **Premium**.
2. Prepare service contract template `TEMPL0002` as a prepaid contract invoiced quarterly.
3. Create three service items for customer `10000`, each using item `S-100`. Refer to them as items A, B, and C.
4. Set the work date to `1 January 2026`.
5. Create a prepaid quarterly service contract for customer `10000` from template `TEMPL0002`, add item A, and run **Sign Contract**.
6. Run **Create Service Invoice**, open the invoice, and post the initial first-quarter invoice for item A.
7. Add the **Invoiced to Date** field to the Service Contract Lines part through personalization or profile configuration.
8. Set the work date to `1 February 2026`, run **Open Contract**, and add item B with a starting date of `1 February 2026`.
9. Run **Lock Contract**. Accept the prompts to process the new line, but decline creation of the retrospective invoice.
10. Set the work date to `1 March 2026`, reopen the contract, and add item C with a starting date of `1 March 2026`.
11. Lock the contract again. Accept the prompts to process the new line, but decline invoice creation.
12. Set the work date to `1 April 2026` and run **Create Service Invoice**. Confirm creation of the retrospective invoice for February and March.
13. Delete the unposted service invoice and confirm that previous invoice dates should be restored.
14. Run **Create Service Invoice** again and confirm creation of the replacement retrospective invoice.
15. Delete the second unposted service invoice and again confirm restoration of previous invoice dates.
16. Reopen the service contract and inspect **Invoiced to Date** on lines A, B, and C.

## Expected behavior

- Item A retains **Invoiced to Date = 31 March 2026** because its first-quarter invoice was posted.
- Items B and C reset to a blank date because both retrospective invoices were deleted.
- A subsequent service invoice can be created with the correct retrospective periods.

## Actual behavior

After deleting the recreated invoice for the second time, items B and C remain at **Invoiced to Date = 31 March 2026**, preventing the next service invoice from being created correctly.
