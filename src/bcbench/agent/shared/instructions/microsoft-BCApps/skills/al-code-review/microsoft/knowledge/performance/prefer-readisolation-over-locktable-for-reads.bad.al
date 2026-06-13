codeunit 50233 "Perf Sample ReadIso Bad"
{
    procedure GetOrCreate(var AgentStatus: Record "Agent Status")
    begin
        // LockTable poisons every subsequent read of Agent Status in the
        // surrounding transaction with UPDLOCK — even for callers that only read.
        AgentStatus.LockTable();
        if not AgentStatus.Get() then begin
            AgentStatus.Init();
            AgentStatus.Insert();
        end;
    end;
}
