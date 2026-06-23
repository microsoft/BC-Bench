codeunit 50206 "Sec Sample Inherent Bad"
{
    [InherentPermissions(PermissionObjectType::TableData, Database::"Sales Header", 'RIMD')]
    [InherentEntitlements(Entitlement::"Dynamics 365 Business Central Premium")]
    procedure GetCustomerName(CustomerNo: Code[20]): Text
    var
        Customer: Record Customer;
    begin
        if Customer.Get(CustomerNo) then
            exit(Customer.Name);
    end;

    [InherentEntitlements(Entitlement::"Dynamics 365 Business Central Premium")]
    procedure CheckItemExists(ItemNo: Code[20]): Boolean
    var
        Item: Record Item;
    begin
        exit(Item.Get(ItemNo));
    end;
}
