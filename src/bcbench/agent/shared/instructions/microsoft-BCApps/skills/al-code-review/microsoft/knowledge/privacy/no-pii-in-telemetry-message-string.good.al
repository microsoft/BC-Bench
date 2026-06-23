codeunit 50212 "Privacy Sample Telemetry Good"
{
    procedure LogCustomerProcessed(var Customer: Record Customer)
    begin
        Session.LogMessage('0000', 'Customer record processed', Verbosity::Normal,
            DataClassification::SystemMetadata, TelemetryScope::All,
            'Category', 'Privacy');
    end;

    procedure LogFileError()
    begin
        Session.LogMessage('0001', 'Error processing uploaded file', Verbosity::Error,
            DataClassification::SystemMetadata, TelemetryScope::All);
    end;
}
