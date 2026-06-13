codeunit 50203 "Sample Label Comment Bad"
{
    var
        DocumentErrorErr: Label 'Document %1 has errors in %2.';
        ValidationErr: Label 'Field %1 in table %2 contains invalid value %3.';

    procedure Validate(DocNo: Code[20]; Loc: Code[10])
    begin
        Error(DocumentErrorErr, DocNo, Loc);
    end;
}
