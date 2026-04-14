# OSINT Playbook

OSINT is the misc sub-category most likely to fall to a deliberate checklist.
Most attempts fail because the specialist jumps straight to the deepest
search — trying to identify a dome's architectural style before they ran
`exiftool`. Start cheap. Strip EXIF, reverse-image search, username sweep,
*then* escalate. This skill is for **CTF challenges only** — contrived
puzzles where a CTF author planted a public signal. It is not a real-world
surveillance manual.

## Layer 0 — What kind of artifact?

Classify the input before any tool — the category drives the playbook:

- **Image** (JPG/PNG of a place, building, screenshot, person) → §1.
- **Username** (`@handle`, `user/path`) → §2.
- **Email** → §3.
- **Domain / URL** → §4.
- **Real name** → §5.
- **Document** (PDF / DOCX / XLSX / PPTX / EXE) → §6.
- **Transport identifier** (callsign, IMO, MMSI, tail) → §7.
- **Coordinates / area** → §8.
- **Multi-modal / staged** — decompose with `meta/subtask-decomposition`.

If classification isn't obvious in 60 seconds, **re-read
`./challenge/README.md`** — the prompt almost always names the artifact.

## 1 — Image OSINT (GeoGuessr-style)

### 1.1 EXIF first (always, even if "stripped")

```bash
exiftool ./challenge/img.jpg
exiftool -a -G1 -s ./challenge/img.jpg     # all tags with group, short names
exiftool -ee ./challenge/img.jpg           # extract embedded (thumbnails, RDF)
```

Grep for:
- `GPSLatitude`, `GPSLongitude` → instant win. `exiftool -c "%.6f"` for decimal.
- `GPSAltitude` — often zeroed as a red herring; ignore if lat/lon look real.
- `DateTimeOriginal` + `OffsetTimeOriginal` → UTC offset → rough longitude.
- `Make`, `Model`, `Software` — phone/tool fingerprint.
- `XPComment`, `UserComment`, custom XMP — CTF authors love these.

Embedded thumbnail can survive when main EXIF is stripped:
```bash
exiftool -b -ThumbnailImage img.jpg > thumb.jpg
exiftool thumb.jpg    # re-run — original GPS often lives here
```

### 1.2 Reverse image search

Best geographic coverage first (browser required):

1. **Yandex Images** (https://yandex.com/images/) — strongest for places,
   faces, unbranded buildings.
2. **Google Lens** (https://lens.google) — best for text + consumer products.
3. **Bing Visual Search** (https://www.bing.com/visualsearch) — second opinion.
4. **TinEye** (https://tineye.com) — tracks down the *original* upload
   (useful for stock/news photo attribution).

If the photo is a crop of something larger, recrop tighter on the single
most distinctive feature before submitting. Compute a perceptual hash for
dedup across sites:

```bash
pip install --user pillow imagehash
python3 -c "from PIL import Image; import imagehash; print(imagehash.phash(Image.open('img.jpg')))"
```

### 1.3 Manual landmark / region cues

When reverse search misses, identify region from visible signal:

- **Script** — Cyrillic, Arabic, Hangul, Hanzi (simpl/trad), Devanagari
  → country class.
- **Road markings** — yellow centerline (US, parts of Asia) vs white
  (most of world); solid vs dashed edge lines.
- **License plate** proportions + colour
  (https://en.wikipedia.org/wiki/Vehicle_registration_plate).
- **Power plugs** — A/B (US, JP), C/F (EU), G (UK/IE/MY/SG), I (AU/NZ/CN/AR).
- **Architecture** — onion domes (RU/Bavaria), minarets (Islamic), pagoda
  roofs (E Asia), stilt houses (SE Asia).
- **Vegetation** — palms (tropical), pines (temperate), eucalyptus (AU).
- **Direction signs** — nationally standardised (EU green motorway = IT/ES,
  blue = UK/PT/IE).
- **Vehicles** — Holden=AU, Lada=ex-USSR, kei cars=JP, jeepneys=PH.
- **Sun azimuth + shadow length** — timestamp + https://www.suncalc.org
  → latitude band.

### 1.4 Heavy: rooftop / coastline matching

- **Google Earth Pro** — load region, slide historical imagery back.
- **Sentinel Hub Playground** (https://apps.sentinel-hub.com/sentinel-playground/)
  — free recent Sentinel-2.
- **Overpass Turbo** (https://overpass-turbo.eu/) — OSM feature search,
  e.g. all churches with onion domes in Bavaria.

### 1.5 Stop here

30 min on §1.3–1.4 with no match → re-read the prompt. The author
probably left a textual hint you missed.

## 2 — Username enumeration

### 2.1 Quick manual checks

```bash
curl -s "https://api.github.com/users/<name>" | jq
curl -s "https://api.github.com/users/<name>/events/public" | jq '.[].repo.name' | sort -u
curl -sI "https://twitter.com/<name>"                    # 200 = exists
curl -sI "https://www.reddit.com/user/<name>/about.json"
```

### 2.2 Sherlock — cheap + broad (~400 sites)

```bash
pip install --user sherlock-project
sherlock <username> --print-found --timeout 10
```

Cite: https://github.com/sherlock-project/sherlock.

### 2.3 WhatsMyName / maigret — deeper

```bash
# WhatsMyName — JSON-driven, low false positives
git clone --depth 1 https://github.com/WebBreacher/WhatsMyName.git
python3 WhatsMyName/wmn.py -u <username>

# Maigret — ~3000 sites, slow, best for obscure platforms
pip install --user maigret
maigret <username> --html
```

Cite: https://github.com/soxoj/maigret.

### 2.4 namechk (manual browser)

`https://namechk.com/` and `https://namecheckr.com/` — top ~100
platforms. Use only when host has a browser.

### 2.5 Stop here

If a hit reveals the real name, jump to §5. If the prompt implies
"their email", jump to §3 with `<username>@gmail.com` etc.

## 3 — Email / account OSINT

### 3.1 Gravatar — highest-ROI check

```bash
EMAIL=alice@example.com
HASH=$(printf '%s' "$(echo "$EMAIL" | tr 'A-Z' 'a-z' | tr -d ' ')" | md5sum | cut -d' ' -f1)
curl -s "https://www.gravatar.com/$HASH.json" | jq
# Web profile: https://en.gravatar.com/$HASH
```

Gravatar exposes name, location, linked social profiles — often the
whole identity in one query.

### 3.2 MX sanity

```bash
dig +short MX "$(echo "$EMAIL" | cut -d@ -f2)"
```

### 3.3 holehe — what services has this email registered for?

```bash
pip install --user holehe
holehe alice@example.com
```

Cite: https://github.com/megadose/holehe.

### 3.4 h8mail — breach data

```bash
pip install --user h8mail
h8mail -t alice@example.com
```

Free mode hits HIBP + a few indices. Cite: https://github.com/khast3x/h8mail.

### 3.5 HIBP manual / hunter.io

- `https://haveibeenpwned.com/account/<email>` — no API key.
- `https://hunter.io/email-finder` — company email patterns; free tier
  rate-limited; one query usually enough.

### 3.6 Stop here

Once a gravatar or HIBP hit links to social accounts, **read them** —
don't enumerate further. The flag is almost always in a pinned post, bio,
or linked profile field.

## 4 — Domain / DNS OSINT

### 4.1 Standard records

```bash
apt install -y whois          # not in image by default
whois example.com | grep -iE 'registrar|created|email|name server'

dig ANY  example.com +short
dig TXT  example.com +short    # SPF, DKIM, DMARC, verification tokens
dig MX   example.com +short
dig CAA  example.com +short
dig NS   example.com +short
host example.com
```

TXT often includes `google-site-verification=`, `MS=` (Azure) etc. —
confirms what cloud services the org uses.

### 4.2 Certificate transparency (CT)

```bash
# All certs — gives subdomains essentially for free
curl -s 'https://crt.sh/?q=%25.example.com&output=json' \
  | jq -r '.[].name_value' | tr ',' '\n' | sort -u
```

`%25` is URL-encoded `%`. Cite: https://crt.sh.

### 4.3 Wayback Machine

```bash
curl -s 'https://web.archive.org/cdx/search/cdx?url=example.com/*&output=json&limit=200' \
  | jq -r '.[1:][] | @tsv'

curl -s 'https://web.archive.org/web/2018*/example.com/admin'
```

Old snapshots often have credentials, internal endpoints, debug pages
removed from the live site. Cite: https://archive.org/help/wayback-api.

### 4.4 Subdomain brute (no heavy tools)

```bash
WORDLIST=/usr/share/dnsenum/dns-big.txt
while read sub; do
  dig +short "$sub.example.com" | grep -q . && echo "$sub.example.com"
done < <(head -1000 "$WORDLIST")
```

If needed, install the real tools:
```bash
go install -v github.com/owasp-amass/amass/v4/...@master
go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
```

### 4.5 Shodan / Censys

No keys in image. Keyless fallback:
```bash
curl -s "https://internetdb.shodan.io/$(dig +short example.com | head -1)"
```
Returns open ports + tags.

### 4.6 Stop here

If `crt.sh` + Wayback miss after 5 min, you're looking at the wrong
domain. Re-read prompt.

## 5 — Real name → social

LinkedIn, Twitter/X, Instagram, TikTok, Facebook have no decent
unauthenticated APIs. Use these fallbacks:

### 5.1 GitHub by name

```bash
gh api 'search/users?q=fullname:"Alice Example"' | jq '.items[].login'
gh api 'search/commits?q=author-name:"Alice Example"' \
  -H 'Accept: application/vnd.github.cloak-preview+json' \
  | jq '.items[] | {repo: .repository.full_name, sha: .sha, msg: .commit.message}'
```

Commit search often surfaces the email they commit with.

### 5.2 Google dorks

```
"Alice Example" site:linkedin.com/in
"Alice Example" site:github.com
"Alice Example" site:twitter.com OR site:x.com
"Alice Example" "@gmail.com"
```

### 5.3 Twitter/X advanced search

`https://twitter.com/search-advanced` — filter `from:`, `to:`, date
range, words. Useful when the prompt quotes a tweet.

### 5.4 Stop here

Real-name search dead-ends fast in CTF context. Can't find in 10 min
→ you're missing a hint; switch to §1/§2 with another artifact.

## 6 — File metadata (non-image)

### 6.1 PDF

```bash
exiftool doc.pdf | grep -iE 'author|creator|producer|title|date|subject'
pdfinfo doc.pdf                          # poppler-utils
pdfimages -all doc.pdf /tmp/pdf-img-     # extract images, then re-run §1
```

`Producer` reveals toolchain ("Microsoft Word 2016", specific lib+version).

### 6.2 Office (docx/xlsx/pptx)

These are ZIP archives:

```bash
unzip -l doc.docx
unzip -p doc.docx docProps/core.xml      # author, last-modified-by, dates
unzip -p doc.docx docProps/app.xml       # application + version
unzip -p doc.docx word/document.xml | head -200
unzip -p doc.docx word/comments.xml 2>/dev/null
unzip -p doc.docx word/footer1.xml 2>/dev/null
```

`<dc:creator>` is original author; `<cp:lastModifiedBy>` is who saved
last — often different people in a leak chain.

Track changes / revisions:
```bash
unzip -p doc.docx word/document.xml | xmllint --format - | grep -iE 'ins|del|comment'
```
Deleted-text-in-strikethrough frequently holds the flag in CTFs.

### 6.3 EXE / binary

```bash
file mystery.exe
strings -n 8 -e l mystery.exe | grep -iE 'pdb|github|http|@|version'
python3 -c "
import pefile, datetime
pe = pefile.PE('mystery.exe')
print(datetime.datetime.utcfromtimestamp(pe.FILE_HEADER.TimeDateStamp))
print('DEBUG:', pe.DIRECTORY_ENTRY_DEBUG if hasattr(pe,'DIRECTORY_ENTRY_DEBUG') else None)
"
```

PDB paths are gold: `D:\Users\johnsmith\proj\debug\foo.pdb` reveals
author username and project layout.

### 6.4 Stop here

Name found → §5. Email found → §3.

## 7 — Flight / ship / vehicle tracking

Public sites, no keys needed for casual use:

- **Flight callsign**: `https://flightaware.com/live/flight/<CALLSIGN>`
- **Tail number**: `https://flightaware.com/live/registration/<TAIL>`
- **ADS-B raw**: https://globe.adsbexchange.com
- **Historical flights (≤7d free)**: https://www.flightradar24.com
- **Ship IMO/MMSI**: `https://www.marinetraffic.com/en/ais/details/ships/<IMO>`
  (backup: https://www.vesselfinder.com)
- **VIN decode** (US-centric, covers imports):
  `https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/<VIN>?format=json`

Tracker doesn't recognise the ID → re-check format. CTFs occasionally use
fictional callsigns; pivot to §5.

## 8 — Satellite imagery

When coords are given and the question is "what was here in 2014?":

- **Google Earth Pro** — historical slider (1980s+ in some regions);
  `apt install google-earth-pro` + X11 forwarding.
- **Sentinel-2 via Sentinel Hub Playground** — free, 2015–present, ~10 m:
  https://apps.sentinel-hub.com/sentinel-playground/
- **NASA Worldview** — daily MODIS, good for atmospheric events (fires,
  plumes): https://worldview.earthdata.nasa.gov
- **Planet Labs** — ~3 m daily, commercial; free tier CA-only. Skip.
- **OpenAerialMap** — community drone/aerial: https://openaerialmap.org

Terrain/feature search → OpenStreetMap + Overpass (§1.4). Budget 20 min;
miss → pivot to §1.

## 9 — Language / timezone inference

Do in parallel with §1 reverse search:

- **OCR + language ID**: `tesseract img.png - -l eng+chi_sim+ara`
  (`apt install tesseract-ocr` + lang packs), then
  `pip install --user langdetect`.
- **UTC offset → longitude**: `+05:30` → India, `+09:00` → JP/KR,
  `-03:00` → AR/BR. **DST-aware**: `+02:00` in June in Europe = CEST
  (central EU); `+02:00` in December = EET or SAST.
- **Day length + season** — long shadows + deep snow at noon = high
  latitude winter. Midnight sun narrows to polar summer bands.

## 10 — CTF-specific patterns (what authors actually do)

Read this first if stuck:

- **EXIF "stripped" but thumbnail survives.** Always
  `exiftool -b -ThumbnailImage` before giving up.
- **Coords present, altitude zeroed.** Don't dismiss GPS as fake — zeroed
  alt is standard misdirection; real lat/lon is usually still real.
- **Author in `docx` core.xml.** "Who wrote this?" → almost always
  `unzip -p file.docx docProps/core.xml`.
- **Public GitHub commit history.** Author + repo name hinted → `git log
  --all` for a credential they pushed, then removed without
  `filter-branch`.
- **Real social behind a fake.** Author posts to TikTok/Instagram from
  their real account with geotag — search the *venue* or *event name*
  on the platform, not the fake handle.
- **Flag format is computed.** Many OSINT flags are
  `flag{<answer in lowercase with underscores>}` or a hash of the
  answer. Re-read the prompt for the exact format spec before submission.
- **Wayback has it.** Current site looks empty → snapshot history is
  almost always richer.
- **Pastebin / gists.** `<username> site:pastebin.com` on Google often
  surfaces years-old dumps.
- **Pinned profile fields.** GitHub bio, pinned tweet, Discord status —
  flag may literally be in the bio. Read profiles in full.
- **Distinctive text as Google query.** Quote a unique shopfront/sign
  word from the image. Authors pick photos with one search-friendly word.

## Tools to pip install on demand

```bash
pip install --user sherlock-project   # username enum, ~400 sites
pip install --user maigret            # username enum, ~3000 sites, slow
pip install --user holehe             # email -> registered services
pip install --user h8mail             # email breach search
pip install --user pillow imagehash   # perceptual image hashing
pip install --user langdetect         # text language ID
pip install --user pefile             # PE/EXE metadata
pip install --user beautifulsoup4 lxml  # HTML scraping
```

Go installs for heavy DNS tools (only if §4.4 brute force misses):
```bash
go install -v github.com/owasp-amass/amass/v4/...@master
go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
go install -v github.com/projectdiscovery/dnsx/cmd/dnsx@latest
```

## Tools already in the image

- `curl`, `wget`, `dig`, `host` — HTTP + DNS basics.
- `whois` — install with `apt install -y whois` (not in base image).
- `exiftool` — image / PDF / Office metadata.
- `ffuf`, `gobuster` — content discovery (subdomain/path brute).
- `jq` — every JSON API in this skill uses it.
- `python3` + BeautifulSoup — HTML scraping.
- `tesseract-ocr` — text from images (`apt install tesseract-ocr` + langs).
- `pdfinfo`, `pdfimages` — `apt install poppler-utils`.
- `xmllint` — `apt install libxml2-utils`, pretty-prints Office XML.

## Common traps

- **Compressed/resized images** (WhatsApp, Twitter, Instagram) have EXIF
  stripped. No EXIF ≠ no metadata — thumbnail survives, pHash still hits.
- **Watermarks.** A reverse-image hit on a stock-photo site means the
  author used stock as a *carrier*; the location is the shoot location of
  the original, not the author's. Useful only if shoot location = answer.
- **VPN / stock photo misdirection.** IP geolocates NL but EXIF offset
  `+07:00` = Indonesia. Trust on-image signals over network signals.
- **"OSINT" requiring login** (private Trello board, etc.) is not OSINT —
  it's web/recon with auth. Re-read for a public invite token.
- **Rate limits.** Sherlock, holehe, crt.sh throttle aggressively. Run
  serially or you'll eat 429s for 10 min.
- **Wayback false negatives.** Site not in CDX may still have snapshots —
  try `https://web.archive.org/web/*/example.com/*` in a browser.
- **Faces in CTFs** are almost always public figures or a Wikipedia
  face. Reverse search → Wikipedia → done. Face ID on private individuals
  is out of scope and inappropriate.
- **Flag format.** Re-read the prompt spec before submission — OSINT
  flags are often computed (hash of answer, date format, lat/lon to N
  decimals).

## References

- **OSINT Framework** — visual taxonomy: https://osintframework.com
- **Trace Labs OSINT VM** — preconfigured Kali variant:
  https://www.tracelabs.org/initiatives/osint-vm
- **IntelTechniques tools** — Bazzell index (many require login; cite
  for methodology): https://inteltechniques.com/tools/
- **Bellingcat Online Investigation Toolkit**: https://bit.ly/bcattoolkit
- **PayloadsAllTheThings — OSINT**:
  https://github.com/swisskyrepo/PayloadsAllTheThings
- **Sherlock**: https://github.com/sherlock-project/sherlock
- **WhatsMyName**: https://github.com/WebBreacher/WhatsMyName
- **Maigret**: https://github.com/soxoj/maigret
- **holehe**: https://github.com/megadose/holehe
- **h8mail**: https://github.com/khast3x/h8mail
- **crt.sh**: https://crt.sh
- **Wayback CDX API**: https://archive.org/help/wayback-api
- **CTFAgent (ScienceDirect arxiv)** — RAG pattern for CTF OSINT.
- **Palisade Research arxiv 2412.02776** — re-reading the prompt before
  each deep dive is empirically the highest-EV behaviour change for an
  OSINT agent.

## Stop conditions

- **Flag recovered, format-checked.** Write to `./flag.txt`, emit
  `FLAG: <value>` per triage workflow.
- **Signal in prompt unaddressed after 15 min.** Re-read. "They posted
  from Brazil" + you're searching Russian onion domes = you missed it.
- **Two consecutive layers empty.** Re-classify per Layer 0 — prompt may
  hide a username in filename, email in EXIF `Artist`, URL in PDF meta.
- **Enumerating combinations** (`alice@gmail alice@yahoo ...`) = lost
  thread. Stop, re-read for the specific service hinted.
- **5 failed automated tools, zero hits.** Likely fake/manual-only —
  switch to Google dorks (§5.2).
- **Wall-clock budget exceeded** (CLAUDE.md: 5 min idle = stop). Write
  `./work/postmortem.md` with artifact type, layers tried, hypothesis,
  next pivot.
