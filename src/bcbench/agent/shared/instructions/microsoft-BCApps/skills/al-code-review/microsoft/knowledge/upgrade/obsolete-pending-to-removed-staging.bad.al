// Skipping the Pending stage and going straight to Removed leaves callers
// and persisted rows with no migration window.
enum 50231 "My Enum"
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
}
