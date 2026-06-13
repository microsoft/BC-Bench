enum 50226 "My Enum"
{
    Extensible = true;

    value(0; "First") { }
    value(1; "NewMiddleValue") { } // Inserted in the middle — shifts ordinals.
    value(2; "Second") { }
    value(3; "Third") { }
    // Or: a previously declared value(1; "Second") removed without obsoletion —
    // any persisted "1" now maps to whatever currently occupies ordinal 1.
}
