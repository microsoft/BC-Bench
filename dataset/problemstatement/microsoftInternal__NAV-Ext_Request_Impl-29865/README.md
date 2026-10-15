# [Request for External] Add "var" reference to ItemTempl in event OnBeforeSelectItemTemplate in codeunit 1336 "Item Templ. Mgt."

### Why do you need this change?

Can you please add "var" reference to ItemTempl in event OnBeforeSelectItemTemplate in codeunit 1336 "Item Templ. Mgt."

```
[IntegrationEvent(false, false)]
// >>>>>>>>>>
//local procedure OnBeforeSelectItemTemplate(ItemTempl: Record "Item Templ."; var IsHandled: Boolean; var Result: Boolean)
local procedure OnBeforeSelectItemTemplate(var ItemTempl: Record "Item Templ."; var IsHandled: Boolean; var Result: Boolean)
// <<<<<<<<<<
begin
end;
```

### Describe the request

To be able to filter out templates used for import.
