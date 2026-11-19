# [w1][Table][27][Item] Expose UpdateMyItem()

### Why do you need this change?

We are adding a new `"Price/Profit Calculation"` type as `"Price=Cost+Markup"`. Therefore in the validation logic for `"Price/Profit Calculation"` we need to update`"Unit Price"` in My Item table like how `"Price=Cost+Profit"` is doing currently by calling `UpdateMyItem()`

<img width="1353" height="1038" alt="Image" src="https://github.com/user-attachments/assets/558dfcb0-58d1-4511-95bb-88d08ed1e301" />

### Describe the request

Currently the `UpdateMyItem` is a local procedure in `Item.Table.al`. We would like to change it to public procedure please.

<img width="1203" height="669" alt="Image" src="https://github.com/user-attachments/assets/d5073e66-67d1-4215-a6a6-27b688aebe5f" />
