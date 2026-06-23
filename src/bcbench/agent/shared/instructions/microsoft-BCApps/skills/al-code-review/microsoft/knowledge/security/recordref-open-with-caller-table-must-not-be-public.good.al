codeunit 50232 "Sec Sample RecRef Good"
{
    internal procedure ArchiveRecord(RecId: RecordId)
    var
        RecRef: RecordRef;
    begin
        RecRef.Open(RecId.TableNo);
        RecRef.Get(RecId);
        RecRef.Delete();
        RecRef.Close();
    end;

    procedure ArchiveAllowedRecord(RecId: RecordId)
    var
        RecRef: RecordRef;
    begin
        if not IsAllowedTable(RecId.TableNo) then
            Error('Operation not permitted on this table.');
        RecRef.Open(RecId.TableNo);
        RecRef.Get(RecId);
        RecRef.Delete();
        RecRef.Close();
    end;

    local procedure IsAllowedTable(TableNo: Integer): Boolean
    begin
        exit(TableNo in [Database::Customer, Database::Vendor]);
    end;
}
