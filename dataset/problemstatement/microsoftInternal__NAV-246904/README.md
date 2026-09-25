# Posting a mileage expense report fails because the calculated amount is not rounded

## Environment

- US Business Central 28.1 (Platform 28.0.50017.0, Application 28.1.49838.50112).
- Expense Agent (Preview) is installed and configured.

## Reproduction steps

1. Open **Expense Agent Setup**.
2. Set **Standard Rate of Mileage** to `4.32` and select a valid **Default Mileage UOM**.
3. Ensure an expense user exists with a valid employee posting group and expense posting account.
4. Ensure a company-paid expense payment method exists.
5. Create or open an **Expense Category** with **Expense Detail Required** set to **Mileage**, and assign the company-paid payment method.
6. Create a new **Expense Report** for the expense user.
7. Add a line with the mileage expense category.
8. Enter mileage with two decimal places, for example `28.11`, and complete any required trip description or location fields.
9. Submit and approve the expense report.
10. Open the approved expense report and choose **Post**.

## Expected behavior

The mileage amount is rounded using the applicable currency amount-rounding precision, and the expense report posts successfully.

## Actual behavior

Posting fails because the calculated mileage amount retains excess decimal precision:

> Amount 121.42 needs to be rounded in Gen. Journal Line Journal Template Name='', Journal Batch Name='', Line No.='0'.
