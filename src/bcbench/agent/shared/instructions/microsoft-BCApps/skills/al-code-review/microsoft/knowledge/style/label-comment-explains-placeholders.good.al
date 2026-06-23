codeunit 50202 "Sample Label Comment Good"
{
    var
        CustomerNotFoundErr: Label 'Customer %1 does not exist for sales document %2.', Comment = '%1 = Customer No., %2 = Sales Header No.';
        ValidationErr: Label 'Field %1 in table %2 contains invalid value %3.', Comment = '%1 = Field Name, %2 = Table Caption, %3 = Field Value';
        CustomerSimpleLbl: Label 'Customer %1';

    procedure Validate(CustNo: Code[20]; DocNo: Code[20])
    begin
        Error(CustomerNotFoundErr, CustNo, DocNo);
    end;
}
