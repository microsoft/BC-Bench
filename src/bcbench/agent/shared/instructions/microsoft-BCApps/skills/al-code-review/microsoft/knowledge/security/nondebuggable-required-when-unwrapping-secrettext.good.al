codeunit 50213 "Sec Sample NonDebug Good"
{
    [NonDebuggable]
    procedure BuildConnectionString(ApiKey: SecretText): Text
    begin
        exit('Server=db.example.com;Key=' + ApiKey.Unwrap());
    end;

    [NonDebuggable]
    procedure ParseSessionToken(Response: HttpResponseMessage; var SessionToken: SecretText)
    var
        ResponseText: Text;
        JsonObject: JsonObject;
        JsonToken: JsonToken;
    begin
        Response.Content.ReadAs(ResponseText);
        JsonObject.ReadFrom(ResponseText);
        JsonObject.Get('access_token', JsonToken);
        SessionToken := JsonToken.AsValue().AsText();
    end;
}
