codeunit 50205 "Privacy Sample Direct Error"
{
    procedure ValidateCustomer(var Customer: Record Customer)
    var
        InvalidEmailErr: Label 'Customer %1 has an invalid e-mail address: %2.', Comment = '%1 = Customer No., %2 = E-Mail';
    begin
        if not Customer."E-Mail".Contains('@') then
            Error(InvalidEmailErr, Customer."No.", Customer."E-Mail");
    end;
}
