codeunit 50206 "Sample Error Params Good"
{
    var
        CustomerNotFoundErr: Label 'Customer %1 does not exist.';

    procedure CheckCustomer(CustomerNo: Code[20])
    var
        Customer: Record Customer;
    begin
        if not Customer.Get(CustomerNo) then
            Error(CustomerNotFoundErr, CustomerNo);
    end;
}
