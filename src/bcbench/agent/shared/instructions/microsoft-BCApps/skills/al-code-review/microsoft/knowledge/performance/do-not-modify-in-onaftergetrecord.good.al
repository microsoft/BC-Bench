page 50246 "Perf Sample WriteScroll Good"
{
    PageType = List;
    SourceTable = Customer;

    var
        ShowWarning: Boolean;

    trigger OnAfterGetRecord()
    begin
        ShowWarning := CalcWarning();
    end;

    local procedure CalcWarning(): Boolean
    begin
        exit(false);
    end;
}
