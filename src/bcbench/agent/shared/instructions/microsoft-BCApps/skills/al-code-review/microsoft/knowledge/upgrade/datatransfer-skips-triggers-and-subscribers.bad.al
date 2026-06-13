codeunit 50221 "Upgrade Existing Field"
{
    Subtype = Upgrade;

    local procedure UpdateCustomerCreditLimit()
    var
        Customer: Record Customer;
        DT: DataTransfer;
    begin
        // "Credit Limit (LCY)" has OnValidate logic that recalculates risk fields
        // and notifies subscribers. DataTransfer skips both — derived data drifts.
        DT.SetTables(Database::Customer, Database::Customer);
        DT.AddConstantValue(50000, Customer.FieldNo("Credit Limit (LCY)"));
        DT.CopyFields();
    end;
}
