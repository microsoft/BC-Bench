codeunit 50226 "Sec Sample HtmlEncode Good"
{
    procedure BuildWelcomeHtml(UserName: Text): Text
    var
        SafeName: Text;
    begin
        SafeName := EncodeHtml(UserName);
        exit('<div>Welcome ' + SafeName + '!</div>');
    end;

    local procedure EncodeHtml(Value: Text): Text
    begin
        Value := Value.Replace('&', '&amp;');
        Value := Value.Replace('<', '&lt;');
        Value := Value.Replace('>', '&gt;');
        Value := Value.Replace('"', '&quot;');
        exit(Value);
    end;
}
