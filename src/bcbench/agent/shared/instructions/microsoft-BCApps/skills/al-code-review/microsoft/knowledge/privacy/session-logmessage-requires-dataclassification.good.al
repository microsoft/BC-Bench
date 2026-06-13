codeunit 50210 "Privacy Sample LogMessage Good"
{
    procedure LogCompleted()
    begin
        Session.LogMessage('0003', 'Operation completed', Verbosity::Normal,
            DataClassification::SystemMetadata, TelemetryScope::ExtensionPublisher);
    end;
}
