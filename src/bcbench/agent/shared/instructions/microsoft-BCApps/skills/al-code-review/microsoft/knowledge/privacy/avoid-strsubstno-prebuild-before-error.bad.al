codeunit 50207 "Privacy Sample StrSubstNo Bad"
{
    procedure ReportFailure(var Customer: Record Customer)
    var
        ErrorMsg: Text;
    begin
        ErrorMsg := StrSubstNo('Customer %1 (%2) at %3 has invalid data',
            Customer.Name, Customer."E-Mail", Customer.Address);
        Error(ErrorMsg);
    end;
}
