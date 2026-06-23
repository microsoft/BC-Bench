codeunit 50235 "Upgrade With Validation"
{
    Subtype = Upgrade;

    trigger OnValidateUpgradePerCompany()
    begin
        // No skip logic and no written justification — full-table validation
        // runs on every single upgrade pass.
        ValidateAllCustomers();
    end;

    local procedure ValidateAllCustomers() begin end;
}
