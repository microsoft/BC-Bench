# Possibility to call ProcessProdOrderForReopen from outside

### Why do you need this change?

I would like to develop my own procedure to reopen and reverse a closed production order.

### Describe the request

**Remove the local attribute** from **ProcessProdOrderForReopen**(var ProdOrder: Record "Production Order") so it can be called from outside **Codeunit 5407 "Prod. Order Status Management".**
