page 50248 "Perf Sample TempAPI Good"
{
    PageType = API;
    APIPublisher = 'perf';
    APIGroup = 'sample';
    APIVersion = 'v1.0';
    EntityName = 'outboxEmail';
    EntitySetName = 'outboxEmails';
    SourceTable = "Sent Email";
    SourceTableTemporary = true;
    DelayedInsert = true;
}
