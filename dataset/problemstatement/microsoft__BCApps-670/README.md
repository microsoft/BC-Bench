# #668 Actually return parameters
### Describe the issue
Azure File Share ListDirectory not returning Attributes, Timestamps, ETag if requested.

### Expected behavior
Attributes, Timestamps and ETag must be populated in AFS Directory Content if requested.

### Steps to reproduce
```AL
  var
        afsDirectoryContent: Record "AFS Directory Content";
        response: Codeunit "AFS Operation Response";
        parameters: Codeunit "AFS Optional Parameters";
  begin
        includeProperties.Add(Enum::"AFS Property"::Attributes);
        includeProperties.Add(Enum::"AFS Property"::Timestamps);
        includeProperties.Add(Enum::"AFS Property"::ETag);
        parameters.Include(includeProperties);

        parameters.FileExtendedInfo(true);

        response := AfsFileClient.ListDirectory(path, afsDirectoryContent, parameters);

        if response.IsSuccessful() then begin
            afsDirectoryContent.FindFirst();
            // TestField causes an error as this timestamp (among others) is never populated, never requested
            afsDirectoryContent.TestField("Creation Time");
        end;
    end;
```

### Additional context
The reason for this:
Codeunit 8956 "AFS Optional Parameters"
WRONG:
```AL
    internal procedure GetParameters(): Dictionary of [Text, Text]
    begin
        AFSOptionalParametersImpl.GetParameters();
    end;
```
RIGHT:
```AL
    internal procedure GetParameters(): Dictionary of [Text, Text]
    begin
        exit(AFSOptionalParametersImpl.GetParameters());
    end;
```
