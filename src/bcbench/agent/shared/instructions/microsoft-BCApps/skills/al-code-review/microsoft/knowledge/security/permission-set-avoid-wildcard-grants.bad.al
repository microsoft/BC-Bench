permissionset 50201 "Sec Sample Full Access"
{
    Permissions = tabledata * = RIMD;
}

permissionset 50202 "Sec Sample Basic User"
{
    Permissions = table * = X,
                  tabledata * = R;
}
