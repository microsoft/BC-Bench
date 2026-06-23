codeunit 50245 "Sample Upper Keywords Bad"
{
    procedure Walk(VAR Customer: Record Customer)
    VAR
        Found: Boolean;
    BEGIN
        IF Customer.FindSet() THEN
            REPEAT
                Found := TRUE;
            UNTIL Customer.Next() = 0;
        IF Found THEN
            EXIT;
    END;
}
