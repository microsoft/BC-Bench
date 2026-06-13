page 50247 "Perf Sample WriteScroll Bad"
{
    PageType = List;
    SourceTable = Customer;

    trigger OnAfterGetRecord()
    begin
        // One DB write per row displayed, every time the user scrolls.
        Rec."Reminder Terms Code" := CalcReminderTerms();
        Rec.Modify();
    end;

    local procedure CalcReminderTerms(): Code[10]
    begin
        exit('');
    end;
}
