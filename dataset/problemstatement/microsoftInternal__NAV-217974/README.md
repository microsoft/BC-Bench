# Title: Move Negative Lines on the Sales Order copies the customer address to Shipping to address of the Return Order.
## Repro Steps:
1.  Create a Sales order for customer 20000.
    Take a note of the Shipping address.
    ![Sales Order](./Sales_order.png)
    ![Ship to Default](./ship_to_default.png)
2.  Click On Move Negative Lines.
3.  Choose Return Order.
    ![Move Negative Sales Lines](./move_negative_sales_lines.png)
4.  Open the Return Order.
5.  Shipping Address details are for the customer ( Incorrect).
    ![Shipping and Billing](./shipping_and_billing.png)

**Expected Results:**
*   Shipping address in the Return Order should be the address of Cronus in the settings.
    ![Company Information](./company_information.png)

**Investigation:**
addresses are copied wrongly as in the code of CopyDocumentMgt, transferfield is used. 
  local procedure CopySalesHeaderFromSalesHeader(FromDocType: Enum "Sales Document Type From"; FromSalesHeader: Record "Sales Header"; OldSalesHeader: Record "Sales Header"; var ToSalesHeader: Record "Sales Header")
    begin
        FromSalesHeader.CalcFields("Work Description");
        ToSalesHeader.TransferFields(FromSalesHeader, false);
        UpdateSalesHeaderWhenCopyFromSalesHeader(ToSalesHeader, OldSalesHeader, FromDocType);
        SetReceivedFromCountryCode(FromDocType, ToSalesHeader);
        OnAfterCopySalesHeader(ToSalesHeader, OldSalesHeader, FromSalesHeader, FromDocType);
    end;

## Description:
