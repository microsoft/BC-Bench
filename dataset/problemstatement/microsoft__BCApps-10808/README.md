# Exchange-rate adjustment ledger entry shows the wrong adjustment amount

## Reproduction steps

1. In a W1-localized CRONUS company with EUR as the local currency, open **Currencies** and select `USD`.
2. Ensure **Unrealized Gains Acc.** and **Unrealized Losses Acc.** are populated.
3. Enter these USD exchange rates:
   - `7 April 2026`: EUR 1 = USD `1.1525`
   - `31 May 2026`: EUR 1 = USD `1.1628`
   - `31 July 2026`: EUR 1 = USD `1.1522`
4. Create a purchase invoice for vendor `5000` with:
   - **Posting Date** = `7 April 2026`
   - **Currency Code** = `USD`
   - **VAT Prod. Posting Group** = `NO VAT`
   - Amount = `USD 3,300`
5. Post the invoice.
6. Run **Adjust Exchange Rates** with starting date, ending date, and posting date set to `31 May 2026`, document number `ADJ001`, and currency filter `USD`.
7. Verify that the first adjustment creates an unrealized gain of `EUR 25.36`.
8. Run **Adjust Exchange Rates** again with starting date, ending date, and posting date set to `31 July 2026`, document number `ADJ002`, and currency filter `USD`.
9. Open **Exch. Rate Adjmt. Ledger Entries** and inspect the two entries created by the second adjustment.
10. Compare each row's **Adjustment Amount** with the **Amount (LCY)** of the entry identified by **Detailed Ledger Entry No.**

## Expected behavior

The second adjustment reverses the prior gain and records the remaining loss. Each exchange-rate adjustment ledger row shows the amount of its own linked detailed vendor ledger entry:

- the reversal row shows `-25.36`;
- the remaining loss row shows `-0.75`.

## Actual behavior

The first row of the second adjustment shows **Adjustment Amount = -0.75**, although its linked detailed vendor ledger entry shows **Amount (LCY) = -25.36**. The detailed vendor ledger entries and G/L entries are correct.
