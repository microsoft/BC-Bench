codeunit 50231 "Sec Sample EventGuard Bad"
{
    procedure CheckPermissionsForTable(TableNo: Integer)
    var
        HasAccess: Boolean;
        SkipValidation: Boolean;
    begin
        OnBeforeCheckPermissions(HasAccess, SkipValidation, TableNo);
        if SkipValidation then
            exit;
        if not HasAccess then
            Error('Access denied.');
    end;

    [IntegrationEvent(false, false)]
    local procedure OnBeforeCheckPermissions(var HasAccess: Boolean; var SkipValidation: Boolean; TableNo: Integer)
    begin
    end;
}
