codeunit 50239 "Sample Block Kw Bad"
{
    procedure Dispatch(IsContactName: Boolean; IsSalespersonCode: Boolean)
    var
        i: Integer;
    begin
        if IsContactName then ValidateContactName() else if IsSalespersonCode then ValidateSalespersonCode();
        for i := 1 to 10 do begin DoSomething(i); DoSomethingElse(i); end;
    end;

    local procedure ValidateContactName() begin end;
    local procedure ValidateSalespersonCode() begin end;
    local procedure DoSomething(I: Integer) begin end;
    local procedure DoSomethingElse(I: Integer) begin end;
}
