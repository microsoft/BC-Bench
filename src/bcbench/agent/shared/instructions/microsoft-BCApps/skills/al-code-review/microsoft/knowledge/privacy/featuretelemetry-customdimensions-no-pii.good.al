codeunit 50214 "Privacy Sample FeatureTelemetry Good"
{
    procedure LogUptake()
    var
        FeatureTelemetry: Codeunit "Feature Telemetry";
    begin
        FeatureTelemetry.LogUptake('0000EA2', 'Expense Agent',
            Enum::"Feature Uptake Status"::"Set up");
    end;
}
