Title: [master] W2 2025 - Bug Bash III: [IRIS 1099] Unclear error when trying to send 1099 form document by email to vendor
Repro Steps:
Setup IRS Forms in the US environment. Create an IRS 1099 form document, release it. Click the Send Email action the following error box appears: The vendor has not consented to receive 1099 forms electronically Click the Show Vendor button Update the information on Vendor card: a) set Email for IRS b) set Receiving 1099 E-Form Consent. Go back to the form document Click Send Email Actual Result: the same error box appears Expected result: When "Email for IRS" or "Receiving 1099 E-Form Consent" is updated, show confirm message to user with the text like: Do you want to also update the existing released 1099 form documents? If user agrees, then propagate the email and/or consent to the released 1099 form documents related to this vendor.
Description:
This bug was identified in Bug Bash II for wave 2 2025, you can read details on the Bug Bash here.
