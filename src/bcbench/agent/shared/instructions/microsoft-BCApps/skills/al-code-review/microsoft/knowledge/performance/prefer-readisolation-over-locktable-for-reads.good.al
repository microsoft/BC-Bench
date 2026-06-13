codeunit 50232 "Perf Sample ReadIso Good"
{
    procedure GetOrCreate(var AgentStatus: Record "Agent Status")
    begin
        AgentStatus.ReadIsolation := IsolationLevel::ReadCommitted;
        if not AgentStatus.Get() then begin
            AgentStatus.Init();
            AgentStatus.Insert();
        end;
    end;
}
