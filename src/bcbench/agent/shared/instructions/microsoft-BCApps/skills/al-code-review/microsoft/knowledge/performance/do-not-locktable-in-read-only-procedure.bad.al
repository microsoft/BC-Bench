codeunit 50235 "Perf Sample LockReadOnly Bad"
{
    procedure GetStatus(var AgentStatus: Record "Agent Status"): Boolean
    begin
        // Read-only path, yet every caller's transaction now acquires UPDLOCK
        // on Agent Status for the remainder of the transaction.
        AgentStatus.LockTable();
        exit(AgentStatus.Get());
    end;
}
