permissionset 50200 "Sec Sample Sales Entry"
{
    Permissions = tabledata "Sales Header" = RIM,
                  tabledata "Sales Line" = RIMD,
                  tabledata Customer = R,
                  table "Sales Header" = X,
                  table "Sales Line" = X;
}
