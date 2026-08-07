# Extensibility request: extension point in codeunit 5980 "Service-Post" before posted header creation

## Why this change is needed

The extensibility of codeunit 5980 "Service-Post" is limited compared to codeunit 80 "Sales-Post".
In "Sales-Post", an integration event lets partners override the standard logic that decides whether
a posted invoice or a posted credit memo should be created, using the `IsHandled` pattern.

In "Service-Post" the equivalent decision is hardcoded: when a document is invoiced, the code decides
between preparing a posted service invoice header and a posted service credit memo header purely from
`Service Header."Document Type"`. Because there is no event before this logic, extensions cannot
support custom Service document types that need a different posting flow or a different posted
document.

We need an extension point so partners can replace this decision in a supported, upgrade-safe way,
bringing Service-Post in line with Sales-Post.

## Requested change

Add a new integration event in codeunit 5980 "Service-Post", raised **immediately before** the
standard logic that determines whether a posted service invoice or posted service credit memo is
created (the `if Invoice then ...` block that calls `PrepareInvoiceHeader` / `PrepareCrMemoHeader`).

Use the `IsHandled` pattern, matching the existing behavior in "Sales-Post":

- Declare an `IsHandled: Boolean` local variable and initialize it to `false`.
- Raise the new event before the standard block, passing enough context for a subscriber to take
  over: the `Service Header`, the `IsHandled` flag (by reference), and the posted invoice and credit
  memo numbers (by reference).
- Guard the existing standard block with `if not IsHandled then`, so a subscriber that sets
  `IsHandled := true` fully replaces the standard decision.

Illustrative shape (final event name and signature must follow BC event conventions):

```al
IsHandled := false;
// new integration event raised here, passing Service Header, IsHandled, and the posted document numbers
if not IsHandled then
    if Invoice then
        if ServiceHeader."Document Type" in [ServiceHeader."Document Type"::Order, ServiceHeader."Document Type"::Invoice] then begin
            ServInvoiceNo := ServDocumentsMgt.PrepareInvoiceHeader(Window);
            // ...
        end else begin
            ServCrMemoNo := ServDocumentsMgt.PrepareCrMemoHeader(Window);
            // ...
        end;
```

## Scope

- This codeunit exists in the W1 base layer **and** in the IT and NA layers, which keep their own
  copies of the same posting logic. The change must be applied consistently to every layer that has a
  copy:
  - `App/Layers/W1/BaseApp/Service/Posting/ServicePost.Codeunit.al`
  - `App/Layers/IT/BaseApp/Service/Posting/ServicePost.Codeunit.al`
  - `App/Layers/NA/BaseApp/Service/Posting/ServicePost.Codeunit.al`
- No other layers keep a copy of this codeunit, so only these three files change.
