codeunit 50211 "Sec Sample SecretSubst Good"
{
    procedure BuildAuthHeader(Token: SecretText): SecretText
    begin
        exit(SecretStrSubstNo('Bearer %1', Token));
    end;

    procedure BuildSecretUri(BaseUrl: Text; ApiKey: SecretText): SecretText
    begin
        exit(SecretStrSubstNo('%1?key=%2', BaseUrl, ApiKey));
    end;
}
