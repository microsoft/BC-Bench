codeunit 50220 "Upgrade New Field Init"
{
    Subtype = Upgrade;

    local procedure InitializeNewFlagOnMyTable()
    var
        MyTable: Record "My Table";
        DT: DataTransfer;
    begin
        // "New Flag" is added in the same change as this upgrade procedure.
        // No existing validation logic depends on it, so DataTransfer is safe.
        DT.SetTables(Database::"My Table", Database::"My Table");
        DT.AddConstantValue(true, MyTable.FieldNo("New Flag"));
        DT.CopyFields();
    end;
}
