codeunit 50207 "Sample Error Params Bad"
{
    var
        CustomerNotFoundErr: Label 'Customer %1 does not exist.';

    procedure CheckCustomer(CustomerNo: Code[20])
    var
        Customer: Record Customer;
    begin
        if not Customer.Get(CustomerNo) then
            Error(StrSubstNo(CustomerNotFoundErr, CustomerNo));
        if not Customer.Get(CustomerNo) then
            Error('Customer ' + CustomerNo + ' not found');
    end;
}
