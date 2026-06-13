codeunit 50227 "Sec Sample HtmlEncode Bad"
{
    procedure BuildWelcomeHtml(UserName: Text): Text
    begin
        exit('<div>Welcome ' + UserName + '!</div>');
    end;
}
