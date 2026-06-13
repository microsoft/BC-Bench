codeunit 50227 "Old Method Holder"
{
    [Obsolete('Use NewMethod instead for better performance', '22.0')]
    procedure OldMethod()
    begin
        // Body kept while ObsoleteState = Pending; warns at call sites.
    end;

    procedure NewMethod()
    begin
    end;
}
