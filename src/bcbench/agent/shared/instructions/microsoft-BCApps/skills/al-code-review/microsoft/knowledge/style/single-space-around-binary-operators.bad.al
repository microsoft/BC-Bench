codeunit 50229 "Sample Spaces Op Bad"
{
    procedure Compute(Amount: Decimal; Quantity: Decimal): Decimal
    var
        Price: Decimal;
    begin
        Price:=Amount*Quantity;
        if (Amount>0)and(Quantity>0) then
            exit(Price);
        exit(0);
    end;
}
