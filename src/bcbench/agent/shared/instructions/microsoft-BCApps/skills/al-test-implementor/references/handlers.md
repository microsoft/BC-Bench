# UI Handler Methods

**CRITICAL: Analyze code under test for UI interactions and add required handler methods.**
Tests fail with "Unhandled UI" errors when handlers are missing.

## When Handlers Are Required

Handler methods are required when the code under test triggers any UI interaction:

| Trigger in code under test | Required handler |
|---|---|
| `Confirm()` (reversal, deletion, etc.) | ConfirmHandler |
| `Message()` displaying information | MessageHandler |
| `StrMenu()` for user selection | StrMenuHandler |
| `Page.Run()` (non-modal) | PageHandler |
| `Page.RunModal()`, lookup pages, dialogs | ModalPageHandler |
| `Report.Run()` / `Report.RunModal()` | ReportHandler |
| Report request page | RequestPageHandler |
| `Hyperlink()` | HyperlinkHandler |
| Notification `Send()` | SendNotificationHandler |
| Notification `Recall()` | RecallNotificationHandler |

## Handler Analysis (do this BEFORE implementing test code)

1. Read the procedure being tested and all procedures it calls.
2. Look for: `Confirm()`, `Message()`, `StrMenu()`, `Page.Run()`, `Page.RunModal()`, `Report.Run()`, `Report.RunModal()`, `Hyperlink()`, `Send()` on Notification.
3. For each UI interaction found, create the corresponding handler method.
4. Add handler names to the `[HandlerFunctions]` attribute on the test procedure.

## Handler Signatures

| Handler | Signature |
|---|---|
| ConfirmHandler | `[ConfirmHandler] procedure <Name>(Question: Text[1024]; var Reply: Boolean)` |
| MessageHandler | `[MessageHandler] procedure <Name>(Message: Text[1024])` |
| StrMenuHandler | `[StrMenuHandler] procedure <Name>(Options: Text[1024]; var Choice: Integer; Instruction: Text[1024])` |
| PageHandler | `[PageHandler] procedure <Name>(var <Page>: TestPage "<Page Name>")` |
| ModalPageHandler | `[ModalPageHandler] procedure <Name>(var <Page>: TestPage "<Page Name>")` |
| ReportHandler | `[ReportHandler] procedure <Name>(var <Report>: Report "<Report Name>")` |
| RequestPageHandler | `[RequestPageHandler] procedure <Name>(var RequestPage: TestRequestPage)` |
| HyperlinkHandler | `[HyperlinkHandler] procedure <Name>(Hyperlink: Text[1024])` |
| SendNotificationHandler | `[SendNotificationHandler] procedure <Name>(TheNotification: Notification): Boolean` |
| RecallNotificationHandler | `[RecallNotificationHandler] procedure <Name>(TheNotification: Notification): Boolean` |

## Handler Rules

- Every handler listed in `[HandlerFunctions]` MUST be called during test execution.
- Handler procedures must be placed after local procedures in the codeunit.
- Do NOT verify values inside handler procedures — use `LibraryVariableStorage` to pass data back to the test.
- For simple confirmations, set `Reply := true` to confirm or `Reply := false` to cancel.
- Handler names should be descriptive (e.g., `ConfirmHandlerYes`, `ConfirmHandlerNo`, `PostingMessageHandler`).

## Examples

```AL
[Test]
[HandlerFunctions('ConfirmHandlerYes')]
procedure ReversedEntryHasOppositeAmount()
begin
    // Test code that triggers a confirmation dialog
end;

[ConfirmHandler]
procedure ConfirmHandlerYes(Question: Text[1024]; var Reply: Boolean)
begin
    Reply := true; // Always confirm
end;

[MessageHandler]
procedure MessageHandler(Message: Text[1024])
begin
    // Empty handler to suppress message display
end;
```
