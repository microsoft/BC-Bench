# [Subcontracting] Block changing Prod Order Routing and Components when Subcontracting Transfers exist

## What & why

Prevent unsafe changes when subcontracting transfers are in progress

When a production order has active transfer orders sending components to a subcontractor, users could previously change or delete the related components and routing lines — potentially causing data mismatches between the transfer orders and the production order.

This PR blocks modifications to key fields (item, quantity, supply method, location, etc.) on Prod. Order Components and Prod. Order Routing Lines when transfer orders or stock at the subcontractor location exist. 

## Linked work

Fixes [AB#634269](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/634269)











