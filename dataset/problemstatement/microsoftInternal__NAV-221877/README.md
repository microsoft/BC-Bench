Title: The service order header status field is not being validated properly when new line is added
Repro Steps:
1. Insert a standard item into the service order line
2.Add it to the line, update the status to 'Finished', and then insert a new line
3The new service item with a status of 'Pending', but the service order header status remains 'Finished
4.But if I re-validate the Pending status field on my service line, the header status changes.

Actual Result: The service order header status field is not being validated properly
Expected Result: The expected behavior is that the header status should reflect the priority status automatically when a new lien is added without manual intervention.

Description:
The service order header status field is not being validated properly when new line is added
