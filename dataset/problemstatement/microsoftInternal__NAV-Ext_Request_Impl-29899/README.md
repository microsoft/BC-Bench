# [Event Request] OnQueryClosePage on page 7005 "Price List Line Review"

### Why do you need this change?

When working with Price Lists (sales and purchase) and you change a line you cannot lease the page before accepting the changes. Makes sense to warn the user that the price change is not active.

However, if another user opens the price/discount lines from an item/customer/vendor etc. and draft lines are shown, the page cannot be closed. I think the use case is assuming that the same user make the change - but the draft line may just as well be due to another user making changes to a price list. Having the user approve draft lines created by someone else is very confusing.

Adding the same event we have on the sales/purchase price list to the page 7005 "Price List Line Review" will allow us work around the problem until better handling is added to the feature.

### Describe the request

On **page 7005 "Price List Line Review"** the IsHandled pattern should be added to the **OnQueryClosePage** trigger.

```
        IsHandled := false;
        OnQueryClosePageOnBeforeDraftLineCheck(Rec, Result, IsHandled);
        if IsHandled then
            exit(Result);
```
