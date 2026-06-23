tableextension 50223 "Sec Sample VTR Good" extends Customer
{
    fields
    {
        field(50223; "System Batch ID"; Code[20])
        {
            TableRelation = "Sales Header"."No.";
            ValidateTableRelation = false;
            Editable = false;
        }
        field(50224; "External Customer Ref"; Code[50])
        {
            TableRelation = Customer."No.";
            ValidateTableRelation = false;
            trigger OnValidate()
            var
                Customer: Record Customer;
            begin
                if "External Customer Ref" = '' then
                    exit;
                if not Customer.Get("External Customer Ref") then
                    Error('External customer reference %1 does not exist.', "External Customer Ref");
            end;
        }
    }
}
