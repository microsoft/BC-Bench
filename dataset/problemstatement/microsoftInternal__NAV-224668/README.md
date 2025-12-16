# Title: [Headlines] Certain headlines are not hidden because the record Get fails while attempting to set visibility field to false
## Repro Steps:
Headlines are always created with a headline name + user security id as seen below.

```al
if not Get(HeadlineName, UserSecurityId()) then begin
 Init();
 Validate("Headline Name", HeadlineName);
 Validate("User Id", UserSecurityId());
 if not Insert() then exit;
end;
```


However when a headline fx Overdue invoices are suppose to be hidden, when it tries to find the headline, it does not append the user security id to the Get(<headline>, <user id>). It only uses Get(<headline>) which will always fail.

This does not error out because the error is trapped with a if/else

in file EssentialBusHeadlineMgt.Codeunit.al `if EssentialBusinessHeadline.Get(HeadlineName) then begin`
## Description:
