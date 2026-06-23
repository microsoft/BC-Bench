tableextension 50222 "MyTable Ext" extends "My Table"
{
    fields
    {
        field(50200; "New Flag"; Boolean)
        {
            DataClassification = CustomerContent;
            Caption = 'New Flag';
            InitValue = true;
        }
    }
}

codeunit 50223 "Upgrade MyTable NewFlag"
{
    Subtype = Upgrade;

    trigger OnUpgradePerCompany()
    begin
        UpgradeMyTableNewFlag();
    end;

    local procedure UpgradeMyTableNewFlag()
    var
        MyTable: Record "My Table";
        UpgradeTag: Codeunit "Upgrade Tag";
        DT: DataTransfer;
    begin
        if UpgradeTag.HasUpgradeTag(MyTableNewFlagTag()) then
            exit;

        DT.SetTables(Database::"My Table", Database::"My Table");
        DT.AddConstantValue(true, MyTable.FieldNo("New Flag"));
        DT.CopyFields();

        UpgradeTag.SetUpgradeTag(MyTableNewFlagTag());
    end;

    local procedure MyTableNewFlagTag(): Code[250]
    begin
        exit('MS-123456-MyTable-NewFlag-20240101');
    end;
}
