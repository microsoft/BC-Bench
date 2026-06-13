codeunit 50243 "Sample Redundant Else Bad"
{
    procedure Validate(IsAdjmtBinCodeChanged: Boolean)
    var
        AdjmtBinErr: Label 'Adjustment bin code change not allowed.';
        BinCodeErr: Label 'Bin code change not allowed.';
    begin
        if IsAdjmtBinCodeChanged then
            Error(AdjmtBinErr)
        else
            Error(BinCodeErr);
    end;
}
