codeunit 50230 "Sec Sample EventGuard Good"
{
    procedure CheckPermissionsForTable(TableNo: Integer)
    var
        HasAccess: Boolean;
    begin
        HasAccess := PerformInternalCheck(TableNo);
        if not HasAccess then
            Error('Access denied.');
        OnAfterCheckPermissions(TableNo, HasAccess);
    end;

    local procedure PerformInternalCheck(TableNo: Integer): Boolean
    begin
        exit(true);
    end;

    [IntegrationEvent(false, false)]
    local procedure OnAfterCheckPermissions(TableNo: Integer; HasAccess: Boolean)
    begin
    end;
}
