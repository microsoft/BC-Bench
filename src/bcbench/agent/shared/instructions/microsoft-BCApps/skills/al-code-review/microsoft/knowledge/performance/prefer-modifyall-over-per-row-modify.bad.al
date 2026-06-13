codeunit 50243 "Perf Sample ModifyAll Bad"
{
    procedure ApplyPriceUpdate(NewPrice: Decimal)
    var
        SalesLine: Record "Sales Line";
    begin
        SalesLine.SetRange(Type, SalesLine.Type::Item);
        // N writes when one ModifyAll would do.
        if SalesLine.FindSet() then
            repeat
                SalesLine.Validate("Unit Price", NewPrice);
                SalesLine.Modify(true);
            until SalesLine.Next() = 0;
    end;
}
