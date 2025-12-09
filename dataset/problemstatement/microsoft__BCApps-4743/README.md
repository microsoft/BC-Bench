# Added methods in X509Certificate2 to export the certificate public key

#### Summary
Added methods in X509Certificate2 to export the certificate public key:
- GetCertificatePublicKeyAsBase64String
- GetRawCertDataAsBase64String

Both methods are wrapper around respective .Net methods of the `X509Certificate2` class, with the output encoded in Base64 string.

#### 
Fixes #4238 



Fixes [AB#608914](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/608914)


