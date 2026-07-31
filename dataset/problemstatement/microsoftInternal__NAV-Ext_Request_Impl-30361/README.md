# Extensibility request: extension point in "Job Archive Management".AutoArchiveJob

## Why this change is needed

`Job Archive Management.AutoArchiveJob` decides how a job is archived based on
`Jobs Setup."Archive Jobs"`. Today it only handles the `Always` and `Question` options; any other
value silently does nothing, so there is no way for an extension to plug in custom archive handling
(for example, a partner wants a "Request Page" style flow that collects extra input from the user
during archiving).

We need an extension point so subscribers can react when neither of the standard options applies.

## Requested change

Add an integration event in the `else` branch of the `case Jobs Setup."Archive Jobs"` statement in
`AutoArchiveJob`, so extensions can handle additional archive modes. The event should pass the `Job`
and `Jobs Setup` records to subscribers.

Illustrative shape of the request (final event name and signature must follow BC event conventions):

```al
procedure AutoArchiveJob(var Job: Record Job)
var
    JobSetup: Record "Jobs Setup";
begin
    JobSetup.Get();
    case JobSetup."Archive Jobs" of
        JobSetup."Archive Jobs"::Always:
            StoreJob(Job, false);
        JobSetup."Archive Jobs"::Question:
            ArchiveJob(Job);
        else
            // new integration event raised here, passing Job and Jobs Setup
    end;
end;
```

## Scope

- File: `App/Layers/W1/BaseApp/Projects/Project/Archive/JobArchiveManagement.Codeunit.al`
- This codeunit exists only in the W1 base layer, so the change lives in W1 alone (no country/region
  layer counterparts to propagate to).
