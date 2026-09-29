# Adjustment Amount is inaccurate when an unrealized gain becomes a loss

## Description

The **Adjustment Amount** on **Exch. Rate Adjmt. Ledger Entries** is incorrect when an exchange-rate adjustment first registers an unrealized gain and a subsequent adjustment reverses that gain and records a loss.

## Steps to reproduce

1. In a W1-localized CRONUS company with EUR as the local currency, open **Currencies** and select `USD`.
2. Populate **Unrealized Gains Acc.** and **Unrealized Losses Acc.**.
3. Enter these USD exchange rates:
   - `7 April 2026`: EUR 1 = USD `1.1525`
   - `31 May 2026`: EUR 1 = USD `1.1628`
   - `31 July 2026`: EUR 1 = USD `1.1522`
4. Create and post a purchase invoice for vendor `5000` with:
   - **Posting Date** = `7 April 2026`
   - **Currency Code** = `USD`
   - **VAT Prod. Posting Group** = `NO VAT`
   - Amount = `USD 3,300`
5. Run **Adjust Exchange Rates** with starting date, ending date, and posting date set to `31 May 2026`, document number `ADJ001`, and currency filter `USD`.
6. Verify that the first adjustment creates an unrealized gain of `EUR 25.36`.
7. Run **Adjust Exchange Rates** again with starting date, ending date, and posting date set to `31 July 2026`, document number `ADJ002`, and currency filter `USD`.
8. Open **Exch. Rate Adjmt. Ledger Entries** and inspect the entries created by the second adjustment.
9. Compare each row's **Adjustment Amount** with the **Amount (LCY)** of the entry identified by **Detailed Ledger Entry No.**

## Expected behavior

The second adjustment reverses the prior gain and records the remaining loss:

- the reversal row shows `-25.36`;
- the remaining loss row shows `-0.75`.

Each row displays the amount from its own linked detailed vendor ledger entry.

## Actual behavior

The reversal row shows **Adjustment Amount = -0.75**, although its linked detailed vendor ledger entry shows **Amount (LCY) = -25.36**. The detailed vendor ledger entries and G/L entries are correct.
