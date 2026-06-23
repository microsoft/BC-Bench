codeunit 50233 "Sec Sample RecRef Bad"
{
    procedure ArchiveRecord(RecId: RecordId)
    var
        RecRef: RecordRef;
    begin
        RecRef.Open(RecId.TableNo);
        RecRef.Get(RecId);
        RecRef.Delete();
        RecRef.Close();
    end;
}
