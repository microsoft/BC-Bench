codeunit 50234 "Perf Sample LockReadOnly Good"
{
    procedure GetStatus(var AgentStatus: Record "Agent Status"): Boolean
    begin
        if AgentStatus.Get() then
            exit(true);
        AgentStatus.LockTable();
        if not AgentStatus.Get() then begin
            AgentStatus.Init();
            AgentStatus.Insert();
        end;
        exit(true);
    end;
}
