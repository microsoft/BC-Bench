# [W1][Report][7000086][Batch Settl. Posted Bill Grs.] Add Protected var to some variables

### Why do you need this change?

We need to use some variables from the report extension and we don't have access because of their protection level.



### Describe the request

[W1][Report][7000086][Batch Settl. Posted Bill Grs.]

We need to use this variables to make some controls from a reportextension:

    >>>>>>>>>>>>>>>>>>>>>>>>>>>>
    protected var
          PostingDate: Date;
          DueOnly: Boolean;
    <<<<<<<<<<<<<<<<<<<<<<<<<<<

    var
        Text1100000: Label 'Settling           @1@@@@@@@@@@@@@@@@@@@@@@@\\';
        Text1100001: Label 'Bill Groups        #2######  @3@@@@@@@@@@@@@\';
        Text1100002: Label 'Receiv. Documents  #4######';
        Text1100003: Label '%1 Documents in %2 Bill Groups totaling %3 (LCY) have been settled.';
        Text1100004: Label 'Receivable bill settlement %1/%2';
        {...}
