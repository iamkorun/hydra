# Deep PCAP Analysis

Most pcap CTFs fall to three questions: **what protocols are present**
(`tshark -z io,phs`), **are there transferable objects** that
`--export-objects` can pull out whole (HTTP, SMB, SMTP, TFTP), and **is
the flag buried inside a specific protocol's payload** (HID keystrokes,
DNS exfil, ICMP covert channel, Kerberos hash). Triage first — the
protocol hierarchy tells you where to look, and
`strings cap.pcap | grep -E 'flag\{'` solves a shocking number of "hard"
challenges before you touch tshark.

Hydra ships `tshark`; install `tcpdump` ad-hoc if needed. There is no
Wireshark GUI — everything is headless.

## Layer 0 — Triage

```bash
file ./challenge/*.pcap ./challenge/*.pcapng ./challenge/*.cap
```

Expected output:
- `pcap capture file` — libpcap, classic
- `pcapng capture file` — may carry embedded decryption secrets
- `gzip/bzip2 compressed` — decompress first
- `Microsoft NetMon 2.x capture` — `editcap` converts to pcap

```bash
capinfos ./challenge/cap.pcap
```

Note packet count, duration, encapsulation. `IEEE 802.11` means
wireless — check for WPA handshakes (Layer 5). Tiny capture (<100
packets) — single session; huge (>1M) — narrow by protocol first.

```bash
tshark -r cap.pcap -q -z io,phs
```

**Single most important command.** Prints the protocol hierarchy with
byte counts. Tall bars = where to look. `smb2`/`kerberos` → auth
extraction; `ftp-data`/`http` bulk → object extraction; mostly `dns`
→ suspect tunneling.

```bash
tshark -r cap.pcap -q -z conv,ip          # IP conversations
tshark -r cap.pcap -q -z conv,tcp         # TCP streams (first column = stream index)
tshark -r cap.pcap -q -z conv,udp
tshark -r cap.pcap -T fields -e ip.src -e ip.dst | sort -u | head -50
tshark -r cap.pcap -T fields -e eth.src -e eth.dst | sort -u   # MAC OUI lookup
```

Use the TCP stream index with `-z follow,tcp,ascii,<index>` for a
Wireshark-style "Follow TCP Stream".

## Layer 1 — Cheap wins

```bash
strings -a -n 8 cap.pcap | grep -iE 'flag\{|FLAG\{|CTF\{|picoCTF\{|HTB\{'
strings -a -e l -n 8 cap.pcap | grep -iE 'flag'   # UTF-16LE (Windows)
strings -a -e b -n 8 cap.pcap | grep -iE 'flag'   # UTF-16BE
```

Plaintext flags live in HTTP bodies, chat protocols, DNS queries.
Palisade (arxiv 2412.02776) documents strings-first as the highest-yield
tactic across every forensics category.

Port fingerprinting — instant rough classification:

```bash
tshark -r cap.pcap -T fields -e tcp.dstport -e udp.dstport | sort -nu | head -30
```

CTF-relevant ports: `21` FTP, `23` Telnet, `25/110/143` mail, `53` DNS,
`69` TFTP, `80/443/8080` HTTP, `88` Kerberos, `389/636` LDAP,
`445/139` SMB, `1883/8883` MQTT, `5222` XMPP, `6667` IRC, `5060` SIP,
`3389` RDP, `502` Modbus, `102` S7. Non-standard ports? Trust
dissectors, not ports.

Bulk object export — run unconditionally, it's fast:

```bash
mkdir -p ./work/out
tshark -r cap.pcap --export-objects http,./work/out/http
tshark -r cap.pcap --export-objects smb,./work/out/smb
tshark -r cap.pcap --export-objects smtp,./work/out/smtp
tshark -r cap.pcap --export-objects tftp,./work/out/tftp
ls -la ./work/out/**/* 2>/dev/null
```

Then `file`, `exiftool`, `binwalk`, `strings` every extracted object —
one of them is almost certainly the answer.

## Layer 2 — Plaintext protocols

### HTTP

```bash
tshark -r cap.pcap -Y 'http.request' -T fields \
  -e http.request.method -e http.host -e http.request.uri | head -50
tshark -r cap.pcap -Y 'http.authorization' -T fields -e http.authorization
tshark -r cap.pcap -Y 'http.cookie' -T fields -e http.cookie | sort -u
tshark -r cap.pcap -Y 'http' -T fields -e http.authorization \
  | grep Basic | awk '{print $2}' | base64 -d     # decode Basic Auth
```

POST body bytes via `http.file_data`; multipart uploads come out of
`--export-objects http` as files. If bodies look truncated, reassemble:

```bash
tshark -r cap.pcap -o tcp.desegment_tcp_streams:TRUE \
  -o http.desegment_body:TRUE --export-objects http,./work/out/http
```

For heavy HTTP captures, **NetworkMiner** auto-extracts objects,
credentials, and sessions (install `mono-complete`; download from
netresec.com).

### DNS

```bash
tshark -r cap.pcap -Y 'dns.qry.name' -T fields -e dns.qry.name | sort -u
tshark -r cap.pcap -Y 'dns' -T fields \
  -e dns.qry.name -e dns.qry.type -e dns.resp.type
tshark -r cap.pcap -Y 'dns.txt' -T fields -e dns.qry.name -e dns.txt
```

**DNS exfil tells**: long entropy-heavy subdomain labels, many queries
to one parent domain, sustained NULL/TXT/CNAME flow. Quick check:

```bash
tshark -r cap.pcap -Y 'dns.qry.name' -T fields -e dns.qry.name \
  | awk -F. '{print length($1), $1}' | sort -nr | head
```

Labels >30 chars → tunneling (iodine, dnscat2, dnsexfiltrator). Collect
labels in order, strip parent, concatenate; try base32 (iodine default),
base64, hex.

```python
import base64
labels = [line.split('.')[0] for line in open('qnames.txt')]
payload = ''.join(labels)
print(base64.b32decode(payload.upper() + '=' * ((-len(payload)) % 8)))
```

DoH detection: TCP/UDP 443 to `1.1.1.1`, `8.8.8.8`, `9.9.9.9`,
`dns.google`, `cloudflare-dns.com`. Without TLS decryption DoH is
opaque, but its presence is often the answer ("find the exfil channel").

### FTP

```bash
tshark -r cap.pcap -Y 'ftp.request' -T fields \
  -e ftp.request.command -e ftp.request.arg
tshark -r cap.pcap -Y 'ftp.response' -T fields \
  -e ftp.response.code -e ftp.response.arg
tshark -r cap.pcap -Y 'ftp-data' -T fields -e tcp.stream | sort -nu
# Save a data-channel stream as raw bytes:
tshark -r cap.pcap -z follow,tcp,raw,<idx> > ./work/ftp_stream.hex
```

FTP splits control (port 21) from data (random PASV/PORT port); binary
transfers live in `ftp-data`. Strip non-payload lines from raw output,
then `xxd -r -p` back to binary.

### Telnet

```bash
tshark -r cap.pcap -Y 'telnet' -T fields -e telnet.data
tshark -r cap.pcap -z follow,tcp,ascii,<stream_index>
```

Typed chars are echoed → output looks doubled. Backspace (`0x08`)
deletes the prior echoed character.

### SSH

Payloads are encrypted. You get version + algorithms only:

```bash
tshark -r cap.pcap -Y 'ssh' -T fields -e ssh.protocol -e ssh.message_code
```

Flag is rarely in SSH payload; sometimes the version string hints at a
CVE. Move on.

### IRC / XMPP / MQTT

```bash
tshark -r cap.pcap -Y 'irc' -T fields -e irc.response
tshark -r cap.pcap -Y 'irc.request' -T fields -e irc.request
tshark -r cap.pcap -Y 'xmpp' -T fields -e xmpp.message.body
tshark -r cap.pcap -Y 'mqtt' -T fields \
  -e mqtt.topic -e mqtt.msg -e mqtt.clientid
```

IRC is a classic flag leak spot. MQTT is common in IoT/OT; retained
messages replay to late subscribers.

### Email (SMTP / POP3 / IMAP)

```bash
tshark -r cap.pcap --export-objects smtp,./work/out/smtp
tshark -r cap.pcap -Y 'smtp' -T fields -e smtp.req.parameter
tshark -r cap.pcap -Y 'pop' -z follow,tcp,ascii,<stream>
tshark -r cap.pcap -Y 'imap' -z follow,tcp,ascii,<stream>
```

SMTP bodies are MIME; `--export-objects smtp` writes whole emails and
splits attachments. Manual MIME split:

```python
import email
msg = email.message_from_file(open('./work/out/smtp/mail.eml'))
for part in msg.walk():
    if part.get_content_disposition() == 'attachment':
        open(part.get_filename(), 'wb').write(part.get_payload(decode=True))
```

### SMB / CIFS

```bash
tshark -r cap.pcap -Y 'smb2 or smb' -T fields \
  -e smb2.filename -e smb.file
tshark -r cap.pcap -Y 'smb2.cmd == 3' -T fields -e smb2.tree   # shares
tshark -r cap.pcap -Y 'ntlmssp' -T fields -e ntlmssp.ntlmv2_response.ntproofstr
tshark -r cap.pcap --export-objects smb,./work/out/smb
```

SMB-relay tell: same NTProofStr from host A appears relayed to host C.
Rare in CTFs but memorable.

## Layer 3 — Auth hash extraction

### Kerberos AS-REP roasting — hashcat -m 18200

Pre-auth-disabled accounts leak a crackable AS-REP. Filter:

```bash
tshark -r cap.pcap -Y 'kerberos.msg_type == 11' -T fields \
  -e kerberos.CNameString -e kerberos.realm
```

Extract + crack:

```bash
apt install -y john hashcat
python3 /usr/share/john/krbpa2john.py cap.pcap > asrep.hash
hashcat -m 18200 asrep.hash /usr/share/wordlists/rockyou.txt
```

Hash format: `$krb5asrep$23$user@DOMAIN:checksum$ciphertext`.

### Kerberoasting TGS-REP — hashcat -m 13100 (RC4) / -m 19900 (AES)

```bash
tshark -r cap.pcap -Y 'kerberos.msg_type == 13' -T fields \
  -e kerberos.SNameString
```

### NTLMv2 — hashcat -m 5600

Over SMB, HTTP-NTLM, LDAP, RPC binds. Hash format:
`user::domain:server-challenge:ntproofstr:blob`. Fastest extraction is
`pcredz`:

```bash
pip install --user pcredz
Pcredz -f ./cap.pcap
hashcat -m 5600 ntlmv2.hash /usr/share/wordlists/rockyou.txt
```

Manual via tshark (field names vary by version, try both):

```bash
tshark -r cap.pcap -Y 'ntlmssp' -T fields \
  -e ntlmssp.auth.username -e ntlmssp.auth.domain \
  -e ntlmssp.ntlmv2_response.ntproofstr \
  -e ntlmssp.ntlmv2_response -e ntlmssp.challenge
```

### NTLMv1 — hashcat -m 5500 or Crack.sh rainbow tables

If challenge is `1122334455667788` (deterministic), submit the full
`user::domain:lmresp:ntresp:challenge` to https://crack.sh/ with
`NETNTLMv1` — usually cracked in minutes.

## Layer 4 — USB HID keystroke reconstruction

Classic CTF staple. USB keyboard traffic = 8-byte HID reports on the
interrupt endpoint.

```bash
tshark -r cap.pcap -Y 'usb.transfer_type == 0x01' \
  -T fields -e usbhid.data | tr -d ':'
# Some captures use usb.capdata instead:
tshark -r cap.pcap -Y 'usb.transfer_type == 0x01' \
  -T fields -e usb.capdata | tr -d ':'
```

Each report is `MM 00 KK KK KK KK KK KK`. `MM` modifier byte bits:
`0x01` LCtrl, `0x02` LShift, `0x04` LAlt, `0x08` LGUI, upper nibble =
right side. Bytes 3-8 = up to 6 simultaneously-held keycodes.

**HID Usage Page 7 keycodes**: `0x04-0x1d` = a..z, `0x1e-0x27` = 1..0,
`0x28` Enter, `0x2a` BS, `0x2b` Tab, `0x2c` Space, `0x2d` `-`,
`0x2e` `=`, `0x2f` `[`, `0x30` `]`, `0x31` `\`, `0x33` `;`, `0x34` `'`,
`0x35` `` ` ``, `0x36` `,`, `0x37` `.`, `0x38` `/`, `0x39` CapsLock,
`0x3a-0x45` F1..F12, `0x4f-0x52` Right/Left/Down/Up.

Save `./work/hid_replay.py`:

```python
#!/usr/bin/env python3
# Usage: tshark -r cap.pcap -Y 'usb.transfer_type == 0x01' \
#          -T fields -e usbhid.data | python3 hid_replay.py
import sys

KC = {
    0x04:'a',0x05:'b',0x06:'c',0x07:'d',0x08:'e',0x09:'f',0x0a:'g',
    0x0b:'h',0x0c:'i',0x0d:'j',0x0e:'k',0x0f:'l',0x10:'m',0x11:'n',
    0x12:'o',0x13:'p',0x14:'q',0x15:'r',0x16:'s',0x17:'t',0x18:'u',
    0x19:'v',0x1a:'w',0x1b:'x',0x1c:'y',0x1d:'z',
    0x1e:'1',0x1f:'2',0x20:'3',0x21:'4',0x22:'5',0x23:'6',0x24:'7',
    0x25:'8',0x26:'9',0x27:'0',
    0x28:'\n',0x29:'<ESC>',0x2a:'<BS>',0x2b:'\t',0x2c:' ',
    0x2d:'-',0x2e:'=',0x2f:'[',0x30:']',0x31:'\\',0x33:';',0x34:"'",
    0x35:'`',0x36:',',0x37:'.',0x38:'/',
    0x4f:'<R>',0x50:'<L>',0x51:'<D>',0x52:'<U>',
}
SHIFT = {
    'a':'A','b':'B','c':'C','d':'D','e':'E','f':'F','g':'G','h':'H',
    'i':'I','j':'J','k':'K','l':'L','m':'M','n':'N','o':'O','p':'P',
    'q':'Q','r':'R','s':'S','t':'T','u':'U','v':'V','w':'W','x':'X',
    'y':'Y','z':'Z',
    '1':'!','2':'@','3':'#','4':'$','5':'%','6':'^','7':'&','8':'*',
    '9':'(','0':')',
    '-':'_','=':'+','[':'{',']':'}','\\':'|',';':':',"'":'"',
    '`':'~',',':'<','.':'>','/':'?',
}

out = []
prev = set()
for line in sys.stdin:
    line = line.strip().replace(':', '').replace(' ', '')
    if len(line) < 4:
        continue
    try:
        data = bytes.fromhex(line)
    except ValueError:
        continue
    if len(data) < 3:
        continue
    mod, _ = data[0], data[1]
    shift = bool(mod & 0x22)   # left or right shift
    keys = set(data[2:8]) if len(data) >= 8 else set(data[2:])
    new = keys - prev - {0}
    for k in sorted(new):
        ch = KC.get(k, f'<{k:02x}>')
        if shift and ch in SHIFT:
            ch = SHIFT[ch]
        out.append(ch)
    prev = keys
print(''.join(out))
```

Run it:

```bash
tshark -r cap.pcap -Y 'usb.transfer_type == 0x01' \
  -T fields -e usbhid.data | python3 ./work/hid_replay.py
```

Handle `<BS>` by stripping the previous char if needed.

### Mouse reconstruction

Mouse HID reports are typically 4 bytes: `buttons dx dy wheel`. Stitch
`(dx,dy)` cumulatively to plot the cursor path; the trail often draws
readable text. Scapy + matplotlib:

```python
import matplotlib.pyplot as plt
pts, x, y = [], 0, 0
for line in open('mouse.hex'):
    d = bytes.fromhex(line.strip().replace(':',''))
    if len(d) < 4: continue
    dx = d[1] if d[1] < 128 else d[1] - 256
    dy = d[2] if d[2] < 128 else d[2] - 256
    x += dx; y += dy
    pts.append((x, y))
xs, ys = zip(*pts)
plt.plot(xs, ys); plt.gca().invert_yaxis(); plt.savefig('path.png')
```

## Layer 5 — Covert channels

### ICMP data payloads

```bash
tshark -r cap.pcap -Y 'icmp' -T fields -e icmp.type -e data.data
tshark -r cap.pcap -Y 'icmp.type == 8' -T fields -e data.data | tr -d ':' \
  | while read h; do echo "$h" | xxd -r -p; done
```

Default Linux ping payload is 48 bytes with a timestamp prefix — any
other length or visible ASCII is anomalous. Base64/hex-decode.

### TTL / IP ID / window bit encoding

```bash
tshark -r cap.pcap -Y 'ip' -T fields -e ip.ttl | sort | uniq -c
tshark -r cap.pcap -Y 'tcp' -T fields -e tcp.window_size | sort | uniq -c
```

TTLs like `[65,64,65,65,64,...]` mod-2 = stego bitstream. Reconstruct
and chunk into bytes. Same trick applies to IP ID and TCP window LSBs.

### Long SNI / hostname

```bash
tshark -r cap.pcap -Y 'tls.handshake.type == 1' -T fields \
  -e tls.handshake.extensions_server_name | sort -u
```

SNI is cleartext in the TLS handshake — abnormally long hostnames carry
exfiltrated data analogous to DNS exfil.

### WPA handshakes — hashcat -m 22000

```bash
apt install -y hcxtools hashcat
tshark -r cap.pcap -Y 'eapol' -T fields -e wlan.sa -e wlan.da
hcxpcapngtool -o handshake.22000 cap.pcap
hashcat -m 22000 handshake.22000 rockyou.txt
```

## Layer 6 — TLS decryption

**SSLKEYLOGFILE** works against any cipher suite. If the challenge ships
`keys.log` / `sslkeys.log`:

```bash
tshark -r cap.pcap -o tls.keylog_file:./keys.log \
  --export-objects http,./work/out/http-tls
tshark -r cap.pcap -o tls.keylog_file:./keys.log -Y 'http' -V | head -200
```

pcapng can carry the key log embedded as a Decryption Secrets Block —
tshark auto-uses it. Verify: `capinfos cap.pcapng | grep -i secret`.

**RSA private key** only decrypts when the handshake used non-ephemeral
RSA key exchange. Check suite first:

```bash
tshark -r cap.pcap -Y 'tls.handshake.type == 2' -T fields \
  -e tls.handshake.ciphersuite
```

Any `ECDHE_*` or `DHE_*` suite has forward secrecy → RSA key is
useless, need SSLKEYLOGFILE. TLS 1.3 is always ephemeral. If the suite
is `TLS_RSA_*`:

```bash
tshark -r cap.pcap \
  -o 'uat:rsa_keys_list:"10.0.0.1","443","http","./server.key","",""' \
  --export-objects http,./work/out/tls
```

If UAT form is rejected, append to `~/.config/wireshark/rsa_keys`.

## Layer 7 — SIP / RTP (VoIP)

```bash
tshark -r cap.pcap -Y 'sip' -T fields -e sip.Method -e sip.r-uri.user
tshark -r cap.pcap -q -z rtp,streams
tshark -r cap.pcap -Y 'rtp.ssrc == 0x12345678' \
  -T fields -e rtp.payload | tr -d ':\n' | xxd -r -p > stream.raw
apt install -y sox
sox stream.au -r 8000 -e mu-law -b 8 -c 1 out.wav
```

Once audio, cross-reference `.claude/skills/forensics/stego-checklist.md`
for DTMF, Morse, spectrogram text.

## Layer 8 — Industrial / OT protocols

```bash
tshark -r cap.pcap -Y 'modbus' -T fields \
  -e modbus.func_code -e modbus.reference_num -e modbus.data
tshark -r cap.pcap -Y 's7comm' -T fields -e s7comm.header.rosctr
tshark -r cap.pcap -Y 'dnp3'
tshark -r cap.pcap -Y 'cip'      # CIP/EtherNet/IP (Rockwell)
tshark -r cap.pcap -Y 'bacnet'
```

Watch for **program upload/download** (Modbus func 0x17, S7COMM
BlockDownload) — PLC code often holds the flag.

## Tools in Hydra image

- `tshark` (main), `tcpdump` (ad-hoc), `exiftool`, `binwalk`,
  `sleuthkit`, `strings`, `xxd`, `base64/32`, `python3`

## Install on-demand

```bash
pip install --user scapy pyshark pcredz
apt install -y john hashcat hcxtools sox tcpflow mono-complete
```

`tcpflow` writes each TCP conversation to disk — alternative to
`-z follow,tcp`:

```bash
mkdir -p ./work/flows && cd ./work/flows && tcpflow -r ../../cap.pcap
```

## Common traps

- **pcapng vs pcap**. `editcap -F pcap in.pcapng out.pcap` if a tool
  rejects pcapng.
- **VLAN / GRE / MPLS / VXLAN encapsulation**. Inner protocol hides
  one layer down — `tshark -Y 'gre' -V` and read the dissector tree.
- **Fragmented IP / TCP segments**. Pass
  `-o tcp.desegment_tcp_streams:TRUE -o ip.defragment:TRUE` if HTTP
  bodies look truncated.
- **Non-standard ports**. Classify by dissector, not port — `-Y 'http'`
  matches HTTP on any port.
- **HTTP/2 and HTTP/3**. `-Y 'http2'`, `-Y 'quic'`. HTTP/3 over QUIC
  (UDP 443) needs TLS key material to decrypt.
- **Multi-pcap challenges**. `mergecap -w merged.pcap a.pcap b.pcap`,
  or correlate by `frame.time_epoch`.
- **USB speed mismatches**. Low-speed vs high-speed HID reports
  differ — check `usb.idVendor`/`usb.idProduct` against the vendor
  HID descriptor.
- **Truncated captures (snaplen)**. `capinfos` reports snaplen;
  `96`/`128` means headers only, no payload.

## Useful tshark tricks

- `-T json` for jq/Python:
  ```bash
  tshark -r cap.pcap -T json -Y 'http.request' \
    | jq '.[]._source.layers.http."http.host"' | sort -u
  ```
- `-Y` (display filter, post-dissection) is more expressive than
  `-f` (capture BPF).
- Reassemble TCP end-to-end before export:
  ```bash
  tshark -r cap.pcap -o tcp.desegment_tcp_streams:TRUE \
    -o http.desegment_body:TRUE --export-objects http,./work/out
  ```
- Follow TCP: `-z follow,tcp,{ascii,raw,hex},<idx>`
- List stream indices: `tshark -Y 'http' -T fields -e tcp.stream | sort -nu`
- Full hex: `tshark -r cap.pcap -x | less`
- Field introspection: `tshark -r cap.pcap -V -c 1 | less`

## Stop conditions

- Layer 0 shows single protocol <100 packets → budget 10 min before
  widening scope.
- Layers 1-2 yielded 0 objects and 0 plaintext hits → pivot to Layer 4
  (HID), 5 (covert), or 6 (TLS) based on protocol hierarchy.
- TLS dominates and no keys provided → flag is elsewhere (handshake
  SNI, DNS, ICMP, non-TLS stream).
- Nested pcaps: extracted HTTP object is itself a pcap → recurse.
- After two full passes with no progress, write `./work/postmortem.md`
  with protocol hierarchy + auth crack attempts + strings candidates.

## References

- Wireshark user guide: https://www.wireshark.org/docs/wsug_html_chunked/
- `tshark -G help`, `tshark -G fields`
- SANS posters ("Hunt Evil", "Network Forensics"): https://www.sans.org/posters/
- PayloadsAllTheThings "Network Discovery" + "Network Services Pentesting"
- HackTricks Pentesting Network:
  https://book.hacktricks.wiki/en/pentesting-network/pentesting-network/
- NetworkMiner: https://www.netresec.com/
- `nicolaka/netshoot` container
- arxiv 2412.02776 (Palisade) — strings-first
- arxiv 2408.08926 (Cybench) — pcap tasks in benchmark
- CTFTime writeups tagged `USB HID`, `DNS exfil`
