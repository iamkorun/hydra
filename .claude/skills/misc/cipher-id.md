# Cipher Identification & Solve

Roughly 80% of misc "cipher" challenges in CTF reduce to two sub-tasks:
(1) **identify** the cipher class from surface features, (2) **run** the
matching classical-cipher tool. The hard part is pattern recognition, not
solving. When in doubt, *always* run the cheap sweep first (rot13, base64,
Atbash, common Vigenère keys). The rest of this skill is: signals that
fingerprint each cipher, the minimum-viable solver, and when to give up
and call it custom-crypto instead.

## Layer 0 — What's the charset?

Before any solver, classify the ciphertext alphabet. Run these two
commands on every blob:

```bash
# Byte distribution (which characters appear, how often)
python3 -c "
import sys, collections
b = open('./challenge/ct.txt','rb').read().strip()
print('len=', len(b))
print('unique=', len(set(b)))
c = collections.Counter(b)
for k,v in c.most_common(15):
    print(f'  {v:5d}  {bytes([k])!r}')
print('printable %%:', sum(32<=x<127 for x in b)/len(b)*100)
"

# Hexdump first 128 bytes for eyeball patterns
xxd ./challenge/ct.txt | head
```

Match the charset to a cipher class using this table:

| Charset / signal                        | Likely cipher                              | Jump to |
|-----------------------------------------|--------------------------------------------|---------|
| `[A-Za-z0-9+/=]` only, len % 4 == 0     | base64                                     | §1      |
| `[A-Z2-7=]` only, len % 8 == 0          | base32                                     | §1      |
| `[0-9a-fA-F]` only, even length         | hex (base16)                               | §1      |
| `[1-9A-HJ-NP-Za-km-z]`, no `0OIl`       | base58 (Bitcoin)                           | §1      |
| `[!-u]`, starts `<~` often              | base85 / ascii85                           | §1      |
| `[A-Za-z]`-only blob, uppercase chunks  | Caesar / Vigenère / substitution           | §3–§5   |
| Mixed case, punctuation preserved       | substitution OR Vigenère                   | §4–§5   |
| Dots/dashes/slash separators            | Morse                                      | §2      |
| Letter pairs, even length, no doubles   | Playfair / bigram                          | §6      |
| Only `ADFGVX` (or `ADFGX`)              | ADFGVX                                     | §8      |
| Numbers `1..26` (or `01..26`)           | A1Z26                                      | §10     |
| Two-digit numbers `11..55`              | Polybius 5×5                               | §10     |
| Groups of 5 chars drawn from `{A,B}`    | Bacon cipher                               | §10     |
| Binary `[01]` only, length % 8 == 0     | ASCII / Bacon / custom binary              | §10     |
| `>+-.,<[]`                              | Brainfuck                                  | §2      |
| `Ook. Ook? Ook!`                        | Ook!                                       | §2      |
| Spaces + tabs + newlines only           | Whitespace (lang)                          | §2      |
| `xn--...`                               | Punycode                                   | §1      |
| Non-ASCII emoji bytes                   | base100 or encoded fun                     | §1      |
| QR/barcode image                        | `zbarimg`                                  | §14     |
| Dots raised on 2×3 grid (⠁⠂⠄…)         | Braille                                    | §14     |
| Pigpen / Dancing-men / stick figures    | visual substitution / semaphore            | §14     |

**Always check length patterns:**

- Divisible by **5** → Bacon, 5-letter group padding, rail-fence.
- Divisible by **8** → base32, byte-aligned binary.
- **Even** with no doubled letters → Playfair candidate.
- **Perfect square** blocks (4, 9, 16, 25) → transposition key hint.

**Always re-read** `./challenge/README.md` and any `hints.md` for cipher
names the author dropped ("polyalph", "5×5 key", "rotor"). 30% of cipher
challenges tell you the cipher in the prompt.

## Layer 1 — Try the cheap stuff first

Before any identification, spray the blob through 15 transforms. If one
returns readable English (or the flag format), you're done in 5 seconds.
This is the single highest-EV action in the entire skill.

```python
# ./work/sweep.py — run: python3 ./work/sweep.py ./challenge/ct.txt
import sys, base64, codecs, urllib.parse, re

raw = open(sys.argv[1], 'rb').read().strip()
s = raw.decode('latin1')
FLAG = re.compile(r'[A-Za-z0-9_]+\{[^}]{3,}\}')


def score(b: bytes) -> float:
    if not b:
        return 0.0
    return sum(32 <= x < 127 or x in (9, 10, 13) for x in b) / len(b)


def show(name: str, out) -> None:
    if isinstance(out, str):
        out = out.encode('latin1', 'replace')
    sc = score(out)
    hit = FLAG.search(out.decode('latin1', 'replace'))
    tag = '  FLAG!' if hit else ''
    if sc > 0.85 or hit:
        print(f'[{sc:.2f}] {name}{tag}: {out[:140]!r}')


def rot(text: str, n: int) -> str:
    out = []
    for c in text:
        if 'A' <= c <= 'Z':
            out.append(chr((ord(c) - 65 + n) % 26 + 65))
        elif 'a' <= c <= 'z':
            out.append(chr((ord(c) - 97 + n) % 26 + 97))
        else:
            out.append(c)
    return ''.join(out)


# 1. ROT-N (all 26)
for n in range(1, 26):
    show(f'rot{n}', rot(s, n))

# 2. Atbash
show('atbash', ''.join(
    chr(155 - ord(c)) if 'A' <= c <= 'Z' else
    chr(219 - ord(c)) if 'a' <= c <= 'z' else c
    for c in s))

# 3. ROT47 (ASCII symmetric)
show('rot47', ''.join(
    chr(33 + (ord(c) - 33 + 47) % 94) if 33 <= ord(c) <= 126 else c
    for c in s))

# 4–8. Base decodings
for name, fn in [
    ('b64', base64.b64decode),
    ('b32', base64.b32decode),
    ('b16', base64.b16decode),
    ('b85', base64.b85decode),
    ('a85', base64.a85decode),
]:
    try:
        show(name, fn(raw, casefold=True) if name == 'b32' else fn(raw))
    except Exception:
        pass

# 9. URL decode
try:
    show('urldecode', urllib.parse.unquote(s))
except Exception:
    pass

# 10. Hex
try:
    show('hex', bytes.fromhex(re.sub(r'[^0-9a-fA-F]', '', s)))
except Exception:
    pass

# 11. Reversed
show('reverse', s[::-1])

# 12. Binary → ASCII
if set(s) <= set('01 \n'):
    bits = re.sub(r'\s', '', s)
    try:
        show('bin->ascii', bytes(
            int(bits[i:i+8], 2) for i in range(0, len(bits) - 7, 8)))
    except Exception:
        pass

# 13. Decimal → ASCII (space-separated)
parts = s.split()
if all(p.isdigit() for p in parts) and parts:
    try:
        show('dec->ascii', bytes(int(p) for p in parts if int(p) < 256))
        # A1Z26: 1..26 → A..Z
        nums = [int(p) for p in parts]
        if all(1 <= n <= 26 for n in nums):
            show('a1z26', ''.join(chr(64 + n) for n in nums))
    except Exception:
        pass

# 14. Morse
MORSE = {
    '.-':'A','-...':'B','-.-.':'C','-..':'D','.':'E','..-.':'F','--.':'G',
    '....':'H','..':'I','.---':'J','-.-':'K','.-..':'L','--':'M','-.':'N',
    '---':'O','.--.':'P','--.-':'Q','.-.':'R','...':'S','-':'T','..-':'U',
    '...-':'V','.--':'W','-..-':'X','-.--':'Y','--..':'Z',
    '-----':'0','.----':'1','..---':'2','...--':'3','....-':'4',
    '.....':'5','-....':'6','--...':'7','---..':'8','----.':'9',
}
if set(s) <= set('.-/ \n'):
    try:
        words = s.replace('/', ' / ').split()
        show('morse', ''.join(MORSE.get(w, ' ') for w in words))
    except Exception:
        pass

# 15. Second-layer: b64 -> rot13 (double-encoded is common)
try:
    inner = base64.b64decode(raw).decode('latin1')
    show('b64->rot13', rot(inner, 13))
except Exception:
    pass
```

The sweep decides the next move. If nothing above 0.85 comes out, the
ciphertext is a *classical* cipher or something custom — proceed to the
identification sections.

## 1 — Base encodings (single-step)

| Encoding           | Alphabet / signal                       | Decoder                                      |
|--------------------|-----------------------------------------|----------------------------------------------|
| base64             | `[A-Za-z0-9+/]` + `=` pad               | `base64 -d` / `base64.b64decode`             |
| base64url          | `-` and `_` instead of `+/`             | `base64.urlsafe_b64decode`                   |
| base32             | `[A-Z2-7]` + `=` pad                    | `base32 -d` / `base64.b32decode`             |
| base32hex          | `[0-9A-V]`                              | `base64.b32hexdecode`                        |
| base16 / hex       | `[0-9a-fA-F]`                           | `xxd -r -p` / `bytes.fromhex`                |
| base58             | `[1-9A-HJ-NP-Za-km-z]` (no `0OIl`)      | `pip install --user base58`                  |
| base85 / RFC1924   | `[0-9A-Za-z!#$%&()*+\-;<=>?@^_\`{|}~]`  | `base64.b85decode`                           |
| ascii85 / Adobe    | `[!-u]`, often `<~...~>` framed         | `base64.a85decode(..., adobe=True)`          |
| Z85                | ZeroMQ subset of base85                 | `pip install --user pyzmq` → `z85.decode`    |
| base91             | 91-char, variable length                | `pip install --user base91`                  |
| base100            | emoji bytes (4 bytes per char)          | `pip install --user pybase100`               |
| URL %-encoding     | `%HH` hex escapes                       | `urllib.parse.unquote`                       |
| HTML entities      | `&#NN;`, `&amp;`                        | `html.unescape`                              |
| Quoted-Printable   | `=HH` or trailing `=\n`                 | `quopri.decodestring`                        |
| Punycode           | `xn--...`                               | `bytes.decode('idna')` / `codecs.decode`     |
| uuencode / xxenc   | `begin 644 ...` header, `\`` padding    | `uu.decode` / `xxdecode` online              |
| ROT13 (as base)    | letters shifted 13                      | `codecs.decode(s, 'rot_13')`                 |

Decoders are in Python stdlib (`base64`, `codecs`, `html`, `quopri`,
`urllib.parse`, `uu`) — no install needed for the common ones. For
base58/91/100 install the pip package on demand.

```bash
# Quick shell one-liners
echo -n "$CT" | base64 -d
echo -n "$CT" | base32 -d
echo -n "$CT" | xxd -r -p            # hex -> bytes
printf '%s' "$CT" | python3 -c "import sys,base64; print(base64.a85decode(sys.stdin.read(),adobe=True))"
```

## 2 — Esoteric / "language" ciphers

| Cipher         | Visual signal                         | Decoder                                                 |
|----------------|---------------------------------------|---------------------------------------------------------|
| Morse          | `.`, `-`, `/` or `|` word separators  | Table in sweep above, or https://morsecode.world       |
| Brainfuck      | `><+-.,[]` only                       | `pip install --user brainfuck` / https://copy.sh/brainfuck |
| Ook!           | `Ook. Ook? Ook!` tokens               | Map tokens to BF pairs, then BF decoder                 |
| Whitespace     | *only* space/tab/newline              | `pip install --user whitespace` / https://vii5ard.github.io/whitespace |
| Malbolge       | Near-random ASCII; ships as CTF meme  | https://malbolge.doleczek.pl (don't try to write)       |
| Piet           | Colorful pixel grid (PNG)             | https://www.bertnase.de/npiet/ or online interpreter    |
| JSFuck         | Only `[]()!+`                         | Paste into a JS console                                 |
| Chef           | Recipes with ingredients / methods    | https://www.dangermouse.net/esoteric/chef.html          |
| Shakespeare    | Acts, scenes, verbose speech          | https://shakespearelang.com (niche)                     |

Ook! → Brainfuck mapping:
```python
MAP = {
    'Ook. Ook?': '>', 'Ook? Ook.': '<', 'Ook. Ook.': '+',
    'Ook! Ook!': '-', 'Ook! Ook.': '.', 'Ook. Ook!': ',',
    'Ook! Ook?': '[', 'Ook? Ook!': ']',
}
import re
tokens = re.findall(r'Ook[.!?] Ook[.!?]', open('ct.txt').read())
bf = ''.join(MAP[t] for t in tokens)
```

## 3 — Caesar / ROT-N / Atbash

All live in the Layer-1 sweep. If one of `rot1..rot25` surfaces the flag,
stop. Beyond that:

- **ROT13** is `rot13` specifically (self-inverse).
- **ROT47** cycles 94 printable ASCII chars — surfaces symbols, not just
  letters. Common when the ciphertext has punctuation you wouldn't expect.
- **Atbash** = A↔Z, B↔Y, ... (rot shift of sorts): `chr(155 - ord(c))`
  for A-Z.
- **ROT-N over a different alphabet**: Vigenère with single-char key.
  If ciphertext is base64-shaped but isn't valid b64, try ROT over the
  base64 alphabet.

Shell forms:
```bash
# ROT13
echo "$CT" | tr 'A-Za-z' 'N-ZA-Mn-za-m'
# Atbash
echo "$CT" | tr 'A-Za-z' 'Z-Aa-z' | tr 'a-z' 'z-a'
# All ROT-N in one loop
for n in {1..25}; do
  echo -n "$n: "
  echo "$CT" | tr "A-Za-z" \
    "$(python3 -c "import sys; n=int(sys.argv[1]); \
print(''.join(chr(65+(i-65+n)%26) if 65<=i<=90 else chr(97+(i-97+n)%26) \
for i in range(65,91))+''.join(chr(97+(i-97+n)%26) for i in range(97,123)))" "$n")"
done
```

## 4 — Vigenère (the workhorse)

Vigenère is the single most-common "classical" cipher in CTF. Detection
and solve are well-defined — no guessing needed if the text is long
enough (≥ 200 chars is comfortable).

### 4.1 Detection — Index of Coincidence

IC measures how often random letter pairs match. English plaintext IC is
**~0.065**; uniform random (or Vigenère with long key) IC is **~0.038**.
A Vigenère ciphertext has IC ≈ 0.038–0.045 depending on key length.

```python
from collections import Counter


def ic(text: str) -> float:
    text = ''.join(c.upper() for c in text if c.isalpha())
    n = len(text)
    if n < 2:
        return 0.0
    f = Counter(text)
    return sum(v * (v - 1) for v in f.values()) / (n * (n - 1))


# Vigenère: IC of full text is ~0.04. IC of columns (sliced by key length)
# is ~0.065 when you hit the right key length.
def ic_by_keylen(text: str, max_len: int = 20) -> list[tuple[int, float]]:
    clean = ''.join(c.upper() for c in text if c.isalpha())
    result = []
    for k in range(1, max_len + 1):
        cols = [clean[i::k] for i in range(k)]
        avg = sum(ic(c) for c in cols) / k
        result.append((k, avg))
    return result
```

A sharp jump toward 0.06+ at some key length `k` = likely key length
(also its multiples; pick the smallest).

### 4.2 Detection — Kasiski examination

Find repeated trigrams; the gaps between repetitions are often multiples
of the key length.

```python
import math
from collections import defaultdict


def kasiski(text: str, ngram: int = 3) -> int:
    clean = ''.join(c.upper() for c in text if c.isalpha())
    positions = defaultdict(list)
    for i in range(len(clean) - ngram + 1):
        positions[clean[i:i + ngram]].append(i)
    gaps = []
    for locs in positions.values():
        if len(locs) > 1:
            for i in range(1, len(locs)):
                gaps.append(locs[i] - locs[0])
    if not gaps:
        return 0
    g = gaps[0]
    for x in gaps[1:]:
        g = math.gcd(g, x)
    return g
```

Compare Kasiski's GCD and IC's best length. Agreement = high confidence.

### 4.3 Key recovery — column-wise frequency analysis

Given key length `k`, slice ciphertext into `k` columns. Each column is a
Caesar-shifted English text. Pick the shift that maximises chi-square
against English letter frequencies.

```python
ENGLISH_FREQ = {
    'A':8.17,'B':1.49,'C':2.78,'D':4.25,'E':12.70,'F':2.23,'G':2.02,
    'H':6.09,'I':6.97,'J':0.15,'K':0.77,'L':4.03,'M':2.41,'N':6.75,
    'O':7.51,'P':1.93,'Q':0.10,'R':5.99,'S':6.33,'T':9.06,'U':2.76,
    'V':0.98,'W':2.36,'X':0.15,'Y':1.97,'Z':0.07,
}


def best_shift(column: str) -> int:
    n = len(column)
    counts = [column.count(chr(65 + i)) for i in range(26)]
    best_score, best = float('inf'), 0
    for shift in range(26):
        chi = 0.0
        for i in range(26):
            obs = counts[(i + shift) % 26]
            exp = ENGLISH_FREQ[chr(65 + i)] / 100 * n
            if exp > 0:
                chi += (obs - exp) ** 2 / exp
        if chi < best_score:
            best_score, best = chi, shift
    return best


def vigenere_break(text: str, keylen: int) -> tuple[str, str]:
    clean = ''.join(c.upper() for c in text if c.isalpha())
    cols = [clean[i::keylen] for i in range(keylen)]
    shifts = [best_shift(c) for c in cols]
    key = ''.join(chr(65 + s) for s in shifts)
    out = []
    idx = 0
    for c in text:
        if c.isalpha():
            base = 65 if c.isupper() else 97
            s = shifts[idx % keylen]
            out.append(chr((ord(c) - base - s) % 26 + base))
            idx += 1
        else:
            out.append(c)
    return key, ''.join(out)
```

### 4.4 Hosted tools (when length < 100 or automated fails)

- **dCode Vigenère**: https://www.dcode.fr/vigenere-cipher — auto-detects
  key length and key.
- **Guballa**: https://www.guballa.de/vigenere-solver — solid free solver.
- **CrypTool-Online**: https://www.cryptool.org/en/cto/vigenere-analysis

### 4.5 pycipher library

```bash
pip install --user pycipher
```
```python
from pycipher import Vigenere
Vigenere('KEY').decipher('LXFOPVEFRNHR')  # -> 'BETHETHIRDONE' style
```

Pycipher also implements Autokey, Beaufort (Vigenère with reversed key),
Porta, Gronsfeld — try these variants if Vigenère detection says yes but
the recovered key is gibberish.

### 4.6 Wordlist sweep for common keys

Short known keys (names, flag formats) are a CTF trope. Spray a wordlist:

```python
from pycipher import Vigenere
cands = ['FLAG','KEY','SECRET','CTF','PASSWORD','ADMIN','HYDRA']
# plus /usr/share/dict/words
for w in cands + open('/usr/share/dict/words').read().splitlines():
    if not w.isalpha() or not (3 <= len(w) <= 10):
        continue
    pt = Vigenere(w.upper()).decipher(ct.upper())
    if 'FLAG' in pt or 'CTF' in pt or 'THE' in pt[:50]:
        print(w, pt[:80])
```

## 5 — Simple substitution (mono-alphabetic)

A 1-to-1 permutation of A-Z. Case sometimes preserved, spaces/punctuation
always preserved. IC matches English (~0.065) because letter frequencies
are intact — just relabeled.

### 5.1 Detection signals

- IC ≈ 0.065 (monoalphabetic — frequencies intact).
- Word shapes preserved (same-letter positions within a word). `HELLO`
  → always some `ABCCD`.
- Short words repeat (`THE`, `AND`) — look for 3-letter words that
  appear 10×+.

### 5.2 Hosted auto-solvers (first choice)

- **quipqiup**: https://quipqiup.com — paste, click, done. Handles
  punctuation.
- **dCode substitution**: https://www.dcode.fr/monoalphabetic-substitution
- **substitutioncipher.com** — cryptogram solver.

For a specialist with no browser: run a local hill-climber (§Automated
scoring).

### 5.3 Frequency analysis (manual)

```python
from collections import Counter
ct = open('ct.txt').read().upper()
letters = [c for c in ct if c.isalpha()]
print(Counter(letters).most_common(10))
# English order: E T A O I N S R H L D C U
# Most-frequent ciphertext letter ≈ 'E'; second ≈ 'T'; etc.
```

Also count bigrams (`TH`, `HE`, `IN`, `ER`, `AN`) and trigrams (`THE`,
`AND`, `ING`, `ION`). A ciphertext trigram appearing 5+ times is almost
always `THE`.

### 5.4 Hill-climb solver (no browser)

See §Automated scoring below for the quadgram score function. Standard
substitution hill-climb:

```python
import random, string
ABC = string.ascii_uppercase


def decrypt(ct: str, key: str) -> str:
    tab = str.maketrans(ABC, key)
    return ct.upper().translate(tab)


def solve_substitution(ct: str, score_fn, iters: int = 4000) -> tuple[str, str]:
    key = list(ABC); random.shuffle(key); key = ''.join(key)
    best, best_score = key, score_fn(decrypt(ct, key))
    for _ in range(iters):
        i, j = random.sample(range(26), 2)
        lst = list(best); lst[i], lst[j] = lst[j], lst[i]
        new = ''.join(lst)
        s = score_fn(decrypt(ct, new))
        if s > best_score:
            best_score, best = s, new
    return best, decrypt(ct, best)
```

Run 10 random restarts and keep the best-scoring result. For English
plaintext this converges in ~5 seconds.

## 6 — Playfair (and four-square / two-square / bifid / trifid)

### 6.1 Playfair signals

- **Length is even.**
- Letters only — no digits, no punctuation.
- **No doubled letters in pairs** (Playfair inserts `X` between `LL`).
- `J` never appears (folded into `I`) — or `Q` (other variant).
- Bigram frequency profile differs from mono-alphabetic — repeated
  bigrams more common than random but less than plaintext.

### 6.2 Playfair solve

Given a key, pycipher does the rest:

```python
from pycipher import Playfair
Playfair('MONARCHY').decipher('BMODZBXDNABEK')
```

Without a key:
- **Crib**: if you know a word in plaintext, derive constraints on the
  5×5 key square. Online solvers do this well:
  `https://www.dcode.fr/playfair-cipher`.
- **Hill-climb** over 5×5 key squares with quadgram score. BionsJBion's
  implementation: http://practicalcryptography.com/cryptanalysis/stochastic-searching/cryptanalysis-playfair/

### 6.3 Four-square / two-square / bifid / trifid

| Cipher      | Signal                                            | Solver                              |
|-------------|---------------------------------------------------|-------------------------------------|
| Four-square | Letters only, 2 keys over 25-letter square        | pycipher `FourSquare(k1,k2)`        |
| Two-square  | Similar, two 5×5 squares                          | pycipher `TwoSquare`                |
| Bifid       | Polybius+transposition, period-based              | pycipher `Bifid(key, period)`       |
| Trifid      | 3×3×3 cube (27 chars with `+`), period-based      | pycipher `Trifid(key, period)`      |

Bifid is identifiable by: looks like substitution (IC high, word shapes
broken), but quadgrams don't score high after hill-climbing simple sub.
Break by period sweep (most CTFs use period 5 or 7).

## 7 — Transposition (rail fence, columnar, Scytale)

Plaintext is rearranged, not substituted. IC matches English exactly,
letter frequencies match English exactly, but no words form.

### 7.1 Rail fence

Try rails 2 through 10:

```python
def railfence_decrypt(ct: str, rails: int) -> str:
    if rails == 1:
        return ct
    n = len(ct)
    pattern = [0] * n
    r, d = 0, 1
    for i in range(n):
        pattern[i] = r
        if r == 0:
            d = 1
        elif r == rails - 1:
            d = -1
        r += d
    # Sort indices by rail row, stable → fill order
    order = sorted(range(n), key=lambda i: (pattern[i], i))
    out = [''] * n
    for src, dst in enumerate(order):
        out[dst] = ct[src]
    return ''.join(out)


for r in range(2, 11):
    candidate = railfence_decrypt(ct, r)
    if 'FLAG' in candidate or 'THE' in candidate[:50]:
        print(r, candidate)
```

### 7.2 Columnar transposition

Brute permutations of column order for small key lengths (≤ 8):

```python
from itertools import permutations


def col_decrypt(ct: str, order: tuple) -> str:
    k = len(order)
    rows = -(-len(ct) // k)    # ceil
    cols = [''] * k
    idx = 0
    for col in order:
        take = rows
        cols[col] = ct[idx:idx + take]; idx += take
    out = ''
    for row in range(rows):
        for col in range(k):
            if row < len(cols[col]):
                out += cols[col][row]
    return out


for k in range(3, 8):
    for p in permutations(range(k)):
        pt = col_decrypt(ct, p)
        if 'FLAG' in pt.upper():
            print(k, p, pt)
```

Beyond k=8 the search explodes — switch to hill-climb on column permutations.

### 7.3 Scytale

Wrap around a cylinder of length `L`; read row by row. Equivalent to
columnar with trivial key. Sweep `L = 2..sqrt(n)`:

```python
import math
for L in range(2, int(math.sqrt(len(ct))) + 2):
    rows = -(-len(ct) // L)
    out = ''.join(ct[r + c * rows] for r in range(rows) for c in range(L)
                  if r + c * rows < len(ct))
    if 'FLAG' in out.upper():
        print(L, out)
```

## 8 — ADFGVX / ADFGX

Fractionation + columnar, popular in CTF because the ciphertext alphabet
is **exactly** `{A,D,F,G,V,X}` (or `{A,D,F,G,X}` in the older version).

### 8.1 Detect

```python
set(ct.upper()) - set('ADFGVX \n') == set()   # ADFGVX
set(ct.upper()) - set('ADFGX \n')  == set()   # ADFGX
```

### 8.2 Solve

Two keys needed: a 6×6 Polybius key (letters + digits, 25 for ADFGX) and
a transposition key. Tools:

- **dCode ADFGVX**: https://www.dcode.fr/adfgvx-cipher — best for
  unknown-key cases.
- **pycipher** does not include ADFGVX; use
  https://github.com/AnthonyF1/ADFGVX-cracker (hill-climb).
- **Featherduster** (archive): https://github.com/nccgroup/featherduster
  — ADFGVX module.

Known key short-circuit:

```python
# Ad-hoc decoder with known keys
POLY_KEY = "MONARCHYBDEFGIKLPQSTUVWXZ0123456789"   # 6x6 or 5x5
TRANSP_KEY = "CARGO"
# 1. Undo transposition using TRANSP_KEY
# 2. Split result into digram pairs of (row, col) letters
# 3. Look up in POLY_KEY square
```

## 9 — Hill cipher

Matrix multiplication mod 26. Identifiable because: ciphertext is
letter-only, block-aligned (length divisible by 2 or 3), and frequency
analysis fails (digraph/trigraph counts look odd).

### 9.1 Known-plaintext key recovery

If you know ≥ `n²` plaintext letters (for `n×n` matrix), compute the key:
`K = C · P⁻¹ (mod 26)`.

```python
import numpy as np


def modinv_matrix(m: np.ndarray, mod: int = 26) -> np.ndarray:
    det = int(round(np.linalg.det(m)))
    det_inv = pow(det % mod, -1, mod)
    adj = np.round(det * np.linalg.inv(m)).astype(int)
    return (det_inv * adj) % mod


def hill_recover_key(pt: str, ct: str, n: int) -> np.ndarray:
    P = np.array([ord(c) - 65 for c in pt[:n*n]]).reshape(n, n)
    C = np.array([ord(c) - 65 for c in ct[:n*n]]).reshape(n, n)
    return (C @ modinv_matrix(P)) % 26
```

### 9.2 Brute force small matrices

`n=2`: 26⁴ = ~450k keys, trivially brute-forceable with a quadgram score.
`n=3`: 26⁹ is too large — need known-plaintext or a crib.

## 10 — Numerical / book ciphers

| Cipher          | Format                              | Decoder                                    |
|-----------------|-------------------------------------|--------------------------------------------|
| A1Z26           | `1 2 3 ...`                         | `chr(64 + n)`                              |
| Polybius 5×5    | `11 12 ... 55`, 2-digit numbers     | row-col lookup in 5×5 square               |
| ASCII decimal   | `72 101 108 ...` (usually > 32)     | `chr(n)`                                   |
| Bacon cipher    | 5-bit `AAAAA..BBBBB` encoding       | Map to 5-bit binary, then to A-Z           |
| Book cipher     | `page.line.word` or `p:l:c`         | Needs the book; check prompt for hint     |
| Tap code        | Pairs like `11 12 13` (1–5, 1–5)    | 5×5 square, K=C                            |

A1Z26 and ASCII decimal are in the Layer-1 sweep. Polybius needs the key
square (often the author encodes it in the prompt).

### 10.1 Bacon cipher

5-letter groups of A and B → binary → character. Two variants:
- **Standard**: 24-letter alphabet (I=J, U=V).
- **Full**: 26-letter.

```python
BACON = {
    'AAAAA':'A','AAAAB':'B','AAABA':'C','AAABB':'D','AABAA':'E',
    'AABAB':'F','AABBA':'G','AABBB':'H','ABAAA':'I','ABAAB':'J',
    'ABABA':'K','ABABB':'L','ABBAA':'M','ABBAB':'N','ABBBA':'O',
    'ABBBB':'P','BAAAA':'Q','BAAAB':'R','BAABA':'S','BAABB':'T',
    'BABAA':'U','BABAB':'V','BABBA':'W','BABBB':'X','BBAAA':'Y','BBAAB':'Z',
}
groups = [ct[i:i+5] for i in range(0, len(ct), 5)]
print(''.join(BACON.get(g, '?') for g in groups))
```

Bacon often arrives *steganographically*: mixed-case text where upper=A,
lower=B. Normalize first.

### 10.2 Book cipher

Unsolvable without the book. Look for:
- Filename hints (`declaration.txt`, `lorem.txt`).
- Prompt refs ("chapter 3 of Moby-Dick").
- Attachments in challenge directory.

Format is typically `page.line.word` or `(page, line, char)`:
```python
# book = open('source.txt').read().split('\n')
# triples = [(2, 5, 3), (1, 10, 1), ...]
# pt = ''.join(book[line-1].split()[word-1][char-1] for page,line,char in triples)
```

## 11 — One-time pad / repeating-key XOR

If key is shorter than message and reused → repeating-key XOR, breakable.
If key is as long as message and used once → unbreakable without a crib.

### 11.1 Detect repeating-key XOR

- Ciphertext is non-ASCII bytes (hex-encoded in challenge).
- Byte distribution is *not* uniform — patterns repeat at key-length
  intervals.

### 11.2 xortool

```bash
pip install --user xortool
xortool -c " " ciphertext.bin           # assume space is most common plaintext
xortool -l 13 -c " " ciphertext.bin     # force key length
```

Cite: https://github.com/hellman/xortool.

### 11.3 Crib drag

If you know (or guess) a plaintext fragment like `flag{`, slide it
along the ciphertext; at the correct offset, the XOR product is the key
fragment.

See exploit template: `exploits/crypto/xor_known_plaintext.py` (already
in the image).

### 11.4 Two-time pad (OTP key reuse)

Two ciphertexts under same key: `c1 XOR c2 = p1 XOR p2`. Frequency
analysis or known-word cribs recover both plaintexts. Similar workflow
to AES-CTR nonce reuse (see `crypto/aes-modes.md`).

## 12 — Enigma / M-209 / rotor machines

Rare in CTF (because they're fiddly), but iconic. Key = rotor choice +
positions + plugboard.

- **Enigma**: 3-5 rotors, reflector, plugboard. Detect by: letter-only
  ciphertext, no letter ever encrypts to itself (true of real Enigma).
  Solver: https://www.cryptii.com → Enigma.
- **crypto-enigma** Python package: `pip install --user crypto-enigma`
  — run configured Enigma.
- **Enigma-Python** (bomba attack): https://github.com/mikepound/enigma
  — 3Blue1Brown / Computerphile companion code; breaks Enigma with
  index-of-coincidence ring settings search.
- **M-209**: pin/lug wheel machine. Use `https://www.cryptomuseum.com/`
  for reference and online simulators.

Enigma challenges almost always give you enough key info in the prompt
(rotor order, starting position); the job is just to run the machine.

## 13 — Other historical ciphers (brief)

| Cipher               | Signal                                   | Tool                                  |
|----------------------|------------------------------------------|---------------------------------------|
| Autokey (Vigenère)   | Vigenère-like but IC sweep misses        | pycipher `Autokey`                    |
| Beaufort             | Vigenère variant (self-inverse)          | pycipher `Beaufort`                   |
| Porta                | Symmetric Vigenère variant               | pycipher `Porta`                      |
| Gronsfeld            | Vigenère with digit key (0-9)            | pycipher `Gronsfeld`                  |
| Affine               | `y = a*x + b mod 26`                     | 26·12 = 312 keys; brute-force         |
| Chaocipher           | Dynamic permutation                      | Crib required; `pycipher.Chaocipher`  |
| Trithemius           | Progressive Caesar (shift += 1)          | Spot-check: `rot_N` with varying N    |

## 14 — Visual / non-text ciphers

### 14.1 QR / barcodes

```bash
apt install -y zbar-tools        # zbarimg provides it
zbarimg --raw ./challenge/cipher.png
```

If `zbarimg` misses:
- Binarize + upscale: `convert cipher.png -resize 400% -threshold 50% clean.png`
- Rotate: QR codes should be upright; `convert -rotate 90`.
- Use `qrazybox` (web) for damaged QR repair:
  https://merri.cx/qrazybox/

### 14.2 Braille

Unicode `⠁..⠿`. Direct map:

```python
BRAILLE = {'⠁':'A','⠃':'B','⠉':'C','⠙':'D','⠑':'E','⠋':'F','⠛':'G','⠓':'H',
           '⠊':'I','⠚':'J','⠅':'K','⠇':'L','⠍':'M','⠝':'N','⠕':'O','⠏':'P',
           '⠟':'Q','⠗':'R','⠎':'S','⠞':'T','⠥':'U','⠧':'V','⠺':'W','⠭':'X',
           '⠽':'Y','⠵':'Z','⠼':'#','⠠':'^'}
```

If the braille is an *image* of dots, OCR via `tesseract` is unreliable;
manually transcribe by quadrants (2 cols × 3 rows dot positions).

### 14.3 Semaphore flags

Images of stick figures with two flags per letter. No good OCR; hand-map
from https://en.wikipedia.org/wiki/Flag_semaphore chart. Often the
challenge provides one letter per image — sequence them manually.

### 14.4 Pigpen / "Freemason"

Grid-corner + tic-tac-toe symbols. No reliable auto-OCR; hand-map:
https://en.wikipedia.org/wiki/Pigpen_cipher

### 14.5 Dancing men

From Sherlock Holmes. Stick-figure map on
https://en.wikipedia.org/wiki/The_Adventure_of_the_Dancing_Men. Hand-map.

### 14.6 Music notation

Notes (C, D, E, F, G, A, B) can encode letters (7-letter alphabet →
pair up for 49 symbols, or use accidentals to extend). Look at the
challenge — if ASCII music notation ("C D E F"), treat as plaintext;
if a PNG staff, OCR with Audiveris or manual.

### 14.7 Sign language / semaphore variants

Hand-sign images → manual lookup. Rare in CTF but shows up in beginner
tracks. ASL fingerspelling chart:
https://en.wikipedia.org/wiki/American_manual_alphabet

## Tools already in the image

- **Python stdlib**: `base64`, `codecs` (includes `rot_13`), `string`,
  `html`, `quopri`, `urllib.parse`, `uu`, `binascii`.
- **pycryptodome**: for XOR with structured keys, any block cipher.
- **gmpy2**, **sympy**: modular arithmetic (Affine, Hill, Polybius).
- **numpy**: linear algebra for Hill cipher.
- **tesseract-ocr**: read text from images (braille/semaphore charts may
  need manual transcription, but ASCII-rendered ciphers OCR fine).
- **`zbarimg`**: via `apt install -y zbar-tools` (not in base image but
  one apt away).

## Install on-demand

```bash
# Classical cipher library (Vigenère, Playfair, Hill, ADFGVX, ...)
pip install --user pycipher

# Repeating-key XOR
pip install --user xortool

# Enigma simulator
pip install --user crypto-enigma

# Less-common base encodings
pip install --user base58 base91 pybase100

# Visual decoders
apt install -y zbar-tools                 # zbarimg for QR/barcodes

# Lattice / automated solvers
pip install --user fpylll flatter         # (pre-installed for crypto)
```

Web-only (no offline equivalent worth porting for a single challenge):
- **dCode.fr** — cipher identifier + 300+ solvers.
- **CyberChef** — https://gchq.github.io/CyberChef/ — "Magic" operation
  tries many transforms automatically.
- **quipqiup** — https://quipqiup.com — auto-sub cryptogram solver.
- **cryptii** — https://cryptii.com — Enigma + many pipelines.
- **Boxentriq** — https://www.boxentriq.com/code-breaking — visual
  cipher identifier.

## Automated scoring (for hill-climb / brute-force)

Most solvers above need a "does this look like English?" function.
Quadgram log-probability is the standard choice.

```python
import math
from collections import defaultdict

# Tiny built-in quadgram table (top ~100). For serious work, download the
# 4.3MB table from http://practicalcryptography.com/media/cryptanalysis/
# files/english_quadgrams.txt.zip and load the same way.

_FALLBACK_QUADGRAMS = """TION 13168379
NTHE 10284332
ATIO 7613307
HERE 5754817
OTHE 5691869
THER 5640031
THAT 5478191
THEI 4898389
FTHE 4769511
DTHE 4598595
INTH 4506569
WITH 4364812""".strip().splitlines()


class QuadgramScorer:
    def __init__(self, path: str | None = None) -> None:
        self.counts: dict[str, int] = defaultdict(int)
        lines = open(path).readlines() if path else _FALLBACK_QUADGRAMS
        for line in lines:
            q, c = line.strip().split()
            self.counts[q] = int(c)
        total = sum(self.counts.values())
        self.log_probs = {q: math.log10(c / total) for q, c in self.counts.items()}
        self.floor = math.log10(0.01 / total)

    def score(self, text: str) -> float:
        s = ''.join(c.upper() for c in text if c.isalpha())
        if len(s) < 4:
            return self.floor * 4
        return sum(
            self.log_probs.get(s[i:i+4], self.floor)
            for i in range(len(s) - 3)
        )
```

Download full quadgrams on demand:
```bash
curl -sL 'http://practicalcryptography.com/media/cryptanalysis/files/english_quadgrams.txt.zip' \
  -o /tmp/quad.zip && unzip -p /tmp/quad.zip > /tmp/quadgrams.txt
```

Higher score = more English-like. Use in any hill-climb (substitution,
Playfair, transposition, Hill key search).

## Common traps

- **Double-encoded blobs.** `base64 → rot13 → ASCII` is a classic author
  trick. Always re-run the sweep on the output of the first sweep.
- **Hint in the prompt.** "Blaise would approve" = Vigenère. "Five by
  five" = Polybius / Playfair. "Round and round" = rotor / rail fence.
  Re-read the README.
- **Non-standard alphabet.** Vigenère over the base64 alphabet (64 chars,
  not 26) is common. Check the ciphertext charset before picking a
  solver — if it's all printable ASCII but non-letter, the alphabet may
  be extended.
- **Length mismatch.** Playfair is *always* even-length. Bifid output
  length matches input. ADFGVX output is letters-only from a 6-char set.
  A length that doesn't fit rules out the cipher.
- **Case preservation.** Case-preserved mixed text usually survives the
  cipher (substitution, Vigenère). Case-stripped UPPERCASE is standard
  for classical. Don't normalize until after you've looked.
- **Non-English plaintext.** Frequency analysis / quadgrams fail for
  Thai, Russian, Chinese, etc. If the prompt is multilingual or
  culturally themed, retarget the frequency table (retrain quadgrams
  from a corpus in that language).
- **Steganographic carrier.** Whitespace-only / case-encoded / invisible
  Unicode (zero-width joiners) are really *stego*, not cipher. Check
  first: `python3 -c "import sys; s=open(sys.argv[1],'rb').read(); \
print(set(s))" ct.txt`.
- **The "cipher" is a URL-decode.** Sometimes `%47%55%45%53%53` is the
  whole puzzle. Run the sweep before reaching for Vigenère.
- **Custom alphabet substitution.** "A=P, B=Z, C=..." mapping given in
  the prompt — not a real cipher, just a `str.translate`.
- **The plaintext is itself encoded.** Decoding Vigenère gives you
  `flag{aGVsbG93b3JsZA==}` — the real flag is base64-inside-flag. Always
  re-check the decoded string for nested encodings.

## References

- **Practical Cryptography** — canonical resource for classical ciphers
  and scoring: http://practicalcryptography.com
- **dCode** — 300+ classical cipher solvers with auto-detect:
  https://www.dcode.fr/en
- **quipqiup** — mono-alphabetic substitution auto-solver:
  https://quipqiup.com
- **CyberChef** — 300+ operations, "Magic" auto-transform:
  https://gchq.github.io/CyberChef/
- **cryptii** — piped ciphers; great for Enigma:
  https://cryptii.com
- **Boxentriq** — cipher identifier + index of dozens of solvers:
  https://www.boxentriq.com/code-breaking
- **pycipher** — Python classical cipher library:
  https://github.com/jameslyons/pycipher
- **xortool** — repeating-key XOR cracker:
  https://github.com/hellman/xortool
- **crypto-enigma** — Enigma simulator:
  https://pypi.org/project/crypto-enigma
- **HackTricks — Cryptography & Cipher Challenges**:
  https://book.hacktricks.wiki/en/crypto-and-stego/cipher-block-chaining-cbc-mac-priv.html
- **CTF Wiki — Classical Cipher**:
  https://ctf-wiki.mahaloz.re/crypto/classical/introduction/
- **Bletchley Park / Enigma tutorials** — for historical context and
  real rotor specs: https://bletchleypark.org.uk
- **Palisade Research arxiv 2412.02776** — shell-first ROT13/base64
  sweep is empirically a strong baseline for "obfuscated text"
  challenges.

## Stop conditions

- **Flag recovered, format-checked.** Write to `./flag.txt`, emit
  `FLAG: <value>` per triage workflow.
- **Layer-1 sweep miss + no identification after 10 min.** The cipher
  may be custom — pivot to `crypto/` specialist (check for key-gen
  code in challenge files) or `rev/` specialist (if a binary does the
  encoding).
- **IC says Vigenère, columns won't align after trying key lengths
  1–40.** Likely a Vigenère *variant* (Autokey, Beaufort, Porta) or a
  *nomenclator* (multi-symbol substitution) — try pycipher variants or
  pivot to rev/crypto.
- **Hill-climb stalls** (quadgram score plateaus well below target
  English levels). The cipher is not mono-sub; re-check for polyalph,
  transposition, or polygram (Playfair/bifid).
- **Non-English plaintext suspected** (charset, prompt theme). Reset
  frequency table; if you can't generate a quadgram table for the
  target language in ≤ 5 min, pivot to OSINT (author's native language)
  or rev.
- **Wall-clock budget exceeded** (CLAUDE.md: 5 min idle = stop). Write
  `./work/postmortem.md` with: ciphertext stats (length, charset, IC),
  identifications tried, why each failed, and what you'd try next
  (custom crypto? rev the encoder?).
