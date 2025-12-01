Title: [ALL-E] [IcM] When creating Pick from a warehouse shipment with FEFO, the Pick Summary page shows wrong 'available to pick' 
Repro Steps:
IcM: Incident-519038327 Details - IcM (microsofticm.com) When the location is set to respect FEFO picking, the quantity available shows a different (wrong) number than when not using FEFO. The available quantity should always be the same, regardless of which order you want to pick the items. In the example below, the qty. should have been 14, which also is shown if not using FEFO. The actual IcM is about the pickable quantity being wrong, not respecting FEFO (expiry dates), but currently (in master) the app doesn't even show the summary, even if it is clearly selected in the 'Whse.-Shipment - Create Pick" batch job: instead it only shows that Pick no. xxxxx has been created.
Description:

