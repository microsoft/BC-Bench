Title: [ALL-E] UX OSS The Production BOM Version has not been certified. Are you sure you want to exit?
Repro Steps:
create new bom with UoM, status New. Add at least one line. Try to close it. You will see message line: The Production BOM has not been certified. Are you sure you want to exit? This is useful message, but what if user wants to disable it. Navigate to My Settings -> My Notifications Search for "Warn..." you can find "Warn about unposted documents" or "Warn about unreleased orders" But there is nothing for Production BOMs, Routings, Versions. Expected: "Warn about non-certified production BOMs and Routings", enabled by default === feature added via OSS. It is useful, but might be annoying for users who for some reason mainly work with non-certified orders.
Description:

