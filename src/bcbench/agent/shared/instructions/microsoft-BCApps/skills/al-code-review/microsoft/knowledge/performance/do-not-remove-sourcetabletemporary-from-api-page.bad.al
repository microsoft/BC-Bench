page 50249 "Perf Sample TempAPI Bad"
{
    PageType = API;
    APIPublisher = 'perf';
    APIGroup = 'sample';
    APIVersion = 'v1.0';
    EntityName = 'outboxEmail';
    EntitySetName = 'outboxEmails';
    SourceTable = "Sent Email";
    // SourceTableTemporary removed — every request now hits SQL.
    DelayedInsert = true;
}
