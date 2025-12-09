# SetSigningKey in SignedXml accepts the key as SecretText

#### Summary
Added methods in SignedXml accepting the signing key as a SecretText:
```
SetSigningKey(XmlString: SecretText)
SetSigningKey(XmlString: SecretText; SignatureAlgorithm: Enum SignatureAlgorithm)
```

#### Work Item(s)
Fixes #4176 



Fixes [AB#596370](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/596370)
