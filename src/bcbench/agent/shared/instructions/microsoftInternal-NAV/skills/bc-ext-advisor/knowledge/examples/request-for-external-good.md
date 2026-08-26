# Request-for-External — Good Examples

Well-formed requests to make existing members externally accessible.

## Example 1: Exposing a procedure

`Codeunit 74 "Reservation Engine Mgt."` contains a `local procedure` that formats a reservation entry description exactly the way the standard UI does. Our extension needs the same formatting to keep our custom pages consistent with the base app. Re-implementing it would duplicate base logic and drift out of sync over time.

The procedure is read-only, performs only formatting/calculation, and accesses no sensitive data — so exposing it is safe and avoids duplicating standard code.

Make `FormatReservationEntry` externally accessible by removing the `local` modifier.

```al
// Before
local procedure FormatReservationEntry(ReservationEntry: Record "Reservation Entry"): Text

// After
procedure FormatReservationEntry(ReservationEntry: Record "Reservation Entry"): Text
```

## Example 2: Exposing a variable

`Table 36 "Sales Header"` keeps the current posting-preview state in a private variable, but our extension needs read access to render an accurate custom preview page. There is no event, protected variable, or public API that surfaces this state today, so extensions cannot build an equivalent preview.

Expose the posting preview state through a protected variable so extension objects that inherit or pair with the base object can read it, without changing any public signature.

```al
// Before
var
    PreviewMode: Boolean;

// After
protected var
    PreviewMode: Boolean;
```
