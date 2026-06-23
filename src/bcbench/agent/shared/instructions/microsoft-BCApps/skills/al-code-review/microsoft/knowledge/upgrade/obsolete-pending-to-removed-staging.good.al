// Release N: deprecation announced.
enum 50229 "My Enum N"
{
    Extensible = true;
    value(0; "First") { }
    value(1; "Second")
    {
        ObsoleteState = Pending;
        ObsoleteReason = 'Replaced by NewValue';
        ObsoleteTag = '22.0';
    }
    value(2; "Third") { }
    value(3; "NewValue") { }
}

// Release N+1 (or later): removal staged; upgrade code now migrates persisted rows.
enum 50230 "My Enum NPlus1"
{
    Extensible = true;
    value(0; "First") { }
    value(1; "Second")
    {
        ObsoleteState = Removed;
        ObsoleteReason = 'Replaced by NewValue';
        ObsoleteTag = '22.0';
    }
    value(2; "Third") { }
    value(3; "NewValue") { }
}
