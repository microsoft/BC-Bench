codeunit 50235 "Sample Begin Own Line Bad"
{
    procedure Run(Condition: Boolean)
    begin
        if Condition then
        begin
            DoSomething();
            DoSomethingElse();
        end;
    end;

    local procedure DoSomething() begin end;
    local procedure DoSomethingElse() begin end;
}
