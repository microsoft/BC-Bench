codeunit 50212 "Sec Sample SecretSubst Bad"
{
    procedure BuildAuthHeader(Token: SecretText): Text
    begin
        exit(StrSubstNo('Bearer %1', Token.Unwrap()));
    end;

    procedure BuildSecretUri(BaseUrl: Text; ApiKey: SecretText): Text
    begin
        exit(BaseUrl + '?key=' + ApiKey.Unwrap());
    end;
}
