codeunit 50213 "Privacy Sample Telemetry Bad"
{
    procedure LogCustomerProcessed(var Customer: Record Customer)
    begin
        Session.LogMessage('0000', StrSubstNo('Processed %1', Customer.Name), Verbosity::Normal,
            DataClassification::SystemMetadata, TelemetryScope::All,
            'Category', 'Privacy');
    end;

    procedure LogFileError(FileName: Text)
    begin
        Session.LogMessage('0001', StrSubstNo('Error processing file %1', FileName), Verbosity::Error,
            DataClassification::SystemMetadata, TelemetryScope::All);
    end;

    procedure LogEmployeeUpdate(EmployeeCode: Code[20])
    begin
        Session.LogMessage('0002', StrSubstNo('Employee %1 updated record', EmployeeCode), Verbosity::Normal,
            DataClassification::SystemMetadata, TelemetryScope::All);
    end;
}
