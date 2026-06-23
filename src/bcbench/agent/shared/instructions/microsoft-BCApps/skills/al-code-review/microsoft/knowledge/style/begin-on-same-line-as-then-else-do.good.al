codeunit 50234 "Sample Begin Same Line Good"
{
    procedure Run(Condition: Boolean)
    var
        i: Integer;
    begin
        if Condition then begin
            DoSomething();
            DoSomethingElse();
        end else begin
            Reset();
            Notify();
        end;
        for i := 1 to 10 do begin
            DoSomething();
            DoSomethingElse();
        end;
    end;

    local procedure DoSomething() begin end;
    local procedure DoSomethingElse() begin end;
    local procedure Reset() begin end;
    local procedure Notify() begin end;
}
