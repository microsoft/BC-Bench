codeunit 50205 "Sec Sample Inherent Good"
{
    [InherentPermissions(PermissionObjectType::TableData, Database::Customer, 'r')]
    procedure GetCustomerName(CustomerNo: Code[20]): Text
    var
        Customer: Record Customer;
    begin
        if Customer.Get(CustomerNo) then
            exit(Customer.Name);
    end;

    [InherentPermissions(PermissionObjectType::TableData, Database::Item, 'r')]
    procedure CheckItemExists(ItemNo: Code[20]): Boolean
    var
        Item: Record Item;
    begin
        exit(Item.Get(ItemNo));
    end;
}
