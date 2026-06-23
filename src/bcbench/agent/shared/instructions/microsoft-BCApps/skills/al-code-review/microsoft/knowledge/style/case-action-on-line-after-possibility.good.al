codeunit 50240 "Sample Case Format Good"
{
    procedure Translate(Letter: Char): Code[10]
    var
        Letter2: Code[10];
    begin
        case Letter of
            'A':
                Letter2 := '10';
            'B':
                Letter2 := '11';
            'C': begin
                Letter2 := '12';
                DoSomething();
            end;
        end;
        exit(Letter2);
    end;

    local procedure DoSomething() begin end;
}
