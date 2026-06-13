codeunit 50215 "Privacy Sample FeatureTelemetry Bad"
{
    procedure LogDocumentReleased(ExpenseHeader: Record "Sales Header"; var User: Record User)
    var
        FeatureTelemetry: Codeunit "Feature Telemetry";
        CustomDimensions: Dictionary of [Text, Text];
    begin
        CustomDimensions.Add('EmployeeNo', ExpenseHeader."Sell-to Customer No.");
        CustomDimensions.Add('UserName', User."Full Name");
        FeatureTelemetry.LogUsage('0000EA1', 'Expense Agent', 'Document Released', CustomDimensions);
    end;
}
