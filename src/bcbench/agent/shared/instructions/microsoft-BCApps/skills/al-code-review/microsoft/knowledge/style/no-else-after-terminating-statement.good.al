codeunit 50242 "Sample No Else Good"
{
    procedure Validate(IsAdjmtBinCodeChanged: Boolean)
    var
        AdjmtBinErr: Label 'Adjustment bin code change not allowed.';
        BinCodeErr: Label 'Bin code change not allowed.';
    begin
        if IsAdjmtBinCodeChanged then
            Error(AdjmtBinErr);
        Error(BinCodeErr);
    end;
}
