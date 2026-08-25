# Codeunit 5812 "Calculate Standard Cost"

### Why do you need this change?

We are migrating a legacy NAV2016 customization for standard cost calculation to Business Central.

1. In NAV2016, partner logic in CalcItem writes detailed cost-calculation lines and depends on values that are finalized only after the manufacturing/assembly calculation step (for example Single-Level Material Cost and Lot Size-driven calculations).

In Business Central, the available CalcItem-related events are before or around user interaction/flow decisions, but there is no dedicated event at the exact point after CalcMfgItem or CalcAssemblyItem has completed and the item cost fields are fully calculated, while still inside the CalcItem orchestration flow.
Because of this missing hook, we cannot reproduce legacy behavior in a clean, upgrade-safe way without copying base logic or moving logic to a less reliable timing point.

Alternatives Evaluated:

OnBeforeCalcItem / OnCalcItemOnBeforeShowStrMenu / OnCalcItemOnAfterCalcShowConfirm
These occur too early. Required cost fields are not finalized yet.

OnCalcMfgItemOnBeforeCalculateCosts and other CalcMfgItem-related events
These are still inside the cost build-up process and do not represent the final post-calculation state needed by the legacy logic in CalcItem.

2. We have another partner logic in CalcProdBOMCost that must run at the end of each loop iteration, after standard calculations are completed for the current Prod. BOM line, but before moving to the next line.
This logic creates detailed cost calculation line entries and depends on values that are finalized within the current iteration (for example computed CompItemQtyBase, CompItem standard cost, and accumulated SLMat).
The currently available events in CalcProdBOMCost are not at this exact timing point, so we cannot reproduce the legacy behavior without intrusive refactoring.

Alternatives evaluated:

Existing OnCalcProdBOMCostOnAfterCalcAnyItem event
This only fires in the Item branch and not as a unified post-iteration hook for the full case block.

Existing events before/after qty calculation
Too early for the required end-of-iteration behavior.

Please add a new IntegrationEvent in CalcProdBOMCost, positioned inside the repeat loop, immediately before the loop-closing line that advances to the next Prod. BOM line.
This should be a true end-of-iteration hook that runs after the case logic for both Type::Item and Type::Production BOM paths.


### Describe the request

1.

    procedure CalcItem(ItemNo: Code[20]; NewUseAssemblyList: Boolean)
    var
         ...
    begin
        ...
        SetProperties(WorkDate(), NewCalcMultiLevel, NewUseAssemblyList, false, '', false);

        if NewUseAssemblyList then begin
            ShowConfirm := NewCalcMultiLevel and AssemblyContainsProdBOM;
            OnCalcItemOnAfterCalcShowConfirm(Item, CalcMfgItems, ShowConfirm);
            if ShowConfirm then
                CalcMfgItems := Confirm(CalcMfgPrompt, false, Item."No.");
            CalcAssemblyItem(ItemNo, Item, 0, CalcMfgItems)
        end else
            CalcMfgItem(ItemNo, Item, 0);
        OnCalcItemOnAfterCalculateCosts(Item); //required event <---
        if TempItem.Find('-') then
            repeat
                ItemCostMgt.UpdateStdCostShares(TempItem);
            until TempItem.Next() = 0;
    end;

    [IntegrationEvent(false, false)]
    local procedure OnCalcItemOnAfterCalculateCosts(Item: Record Item)
    begin
    end;


2.

    local procedure CalcProdBOMCost(MfgItem: Record Item; ProdBOMNo: Code[20]; RtngNo: Code[20]; MfgItemQtyBase: Decimal; IsTypeItem: Boolean; Level: Integer; var SLMat: Decimal; var RUMat: Decimal; var RUCap: Decimal; var RUSub: Decimal; var RUCapOvhd: Decimal; var RUMfgOvhd: Decimal; var SLNonInvMat: Decimal; var RUNonInvMat: Decimal; var SKU: Record "Stockkeeping Unit")
    var
        ...
    begin
        ...
                            end else
                                if MfgCostCalcMgt.CanIncNonInvCostIntoProductionItem() then begin
                                    IncrCost(SLNonInvMat, CompItem."Unit Cost", CompItemQtyBase);
                                    IncrCost(RUNonInvMat, CompItem."Unit Cost", CompItemQtyBase);
                                end;
                            OnCalcProdBOMCostOnAfterCalcAnyItem(ProdBOMLine, MfgItem, MfgItemQtyBase, CompItem, CompItemQtyBase, Level, IsTypeItem, UOMFactor,
                                                                SLMat, RUMat, RUCap, RUSub, RUCapOvhd, RUMfgOvhd);
                        end;
                    ProdBOMLine.Type::"Production BOM":
                        CalcProdBOMCost(
                          MfgItem, ProdBOMLine."No.", RtngNo, CompItemQtyBase, false, Level, SLMat, RUMat, RUCap, RUSub, RUCapOvhd, RUMfgOvhd, SLNonInvMat, RUNonInvMat, SKU);
                end;
                OnCalcProdBOMCostOnBeforeNextLineIteration(ProdBOMLine; PBOMVersionCode, Level, CompItemQtyBase, CompItem, SLMat); // //required event <---
            until ProdBOMLine.Next() = 0;

  [IntegrationEvent(false, false)]
  local procedure OnCalcProdBOMCostOnBeforeNextLineIteration(ProdBOMLine: Record "Production BOM Line", PBOMVersionCode: Code[20]; Level: Integer; CompItemQtyBase: Decimal; CompItem: Record Item; SLMat: Decimal)
  begin
  end;
