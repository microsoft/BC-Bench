codeunit 50234 "Upgrade With Validation"
{
    Subtype = Upgrade;

    trigger OnValidateUpgradePerCompany()
    var
        UpgradeTag: Codeunit "Upgrade Tag";
    begin
        // Justification: regulatory compliance requires a full-table scan once
        // per tenant after this release. Tag prevents re-runs.
        if UpgradeTag.HasUpgradeTag(MyValidationUpgradeTag()) then
            exit;

        ValidateAllCustomers();

        UpgradeTag.SetUpgradeTag(MyValidationUpgradeTag());
    end;

    local procedure ValidateAllCustomers() begin end;

    local procedure MyValidationUpgradeTag(): Code[250]
    begin
        exit('MS-123456-CustomerValidation-20240101');
    end;
}
