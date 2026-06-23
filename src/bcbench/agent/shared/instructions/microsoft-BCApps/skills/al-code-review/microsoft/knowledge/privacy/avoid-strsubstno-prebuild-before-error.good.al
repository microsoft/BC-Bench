codeunit 50206 "Privacy Sample StrSubstNo Good"
{
    procedure ReportFailure(var Customer: Record Customer)
    var
        CustomerInvalidErr: Label 'Customer %1 has invalid data (email: %2).', Comment = '%1 = Customer No., %2 = E-Mail';
    begin
        Error(CustomerInvalidErr, Customer."No.", Customer."E-Mail");
    end;
}
