codeunit 50228 "Sample Spaces Op Good"
{
    procedure Compute(Amount: Decimal; Quantity: Decimal): Decimal
    var
        Price: Decimal;
    begin
        Price := Amount * Quantity;
        if (Amount > 0) and (Quantity > 0) then
            exit(Price);
        exit(0);
    end;
}
