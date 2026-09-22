# [Event Request] Report 99000788 "Prod. Order - Shortage List" - OnAfterCalculateNeededQty

### Why do you need this change?

We would like to add custom calculation and modify the `NeededQty` in the "Prod. Order - Shortage List" report.

### Describe the request

Hi Microsoft BC Dev Team,

Could you add this integration event `OnAfterCalculateNeededQty` to report 99000788 "Prod. Order - Shortage List"?

```
    [IntegrationEvent(false, false)]
    local procedure OnAfterCalculateNeededQty(ProdOrderComponent: Record "Prod. Order Component"; var TempProdOrderLine: Record "Prod. Order Line" temporary; var TempProdOrderComp: Record "Prod. Order Component" temporary; var CompItem: Record Item; var NeededQty: Decimal)
    begin
    end;
```

The event should be placed right after NeededQty is calculated in the report.

<img width="1672" height="919" alt="Image" src="https://github.com/user-attachments/assets/28947c8f-1a61-45ad-a7b3-2d48fde8909b" />

<img width="3304" height="560" alt="Image" src="https://github.com/user-attachments/assets/b8732964-8f38-46b0-9b85-a09c570de062" />



Regards
Tuan
