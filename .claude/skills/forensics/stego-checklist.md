# Stego & Hidden-Data Checklist

Run these in order. Most stego CTFs fall in the first 5 steps.

## 1. Metadata

```bash
exiftool <file>
identify -verbose <img>    # ImageMagick — more detail for images
mediainfo <file>           # for audio/video
```
Look for: Comment, Description, Title, Artist, custom XMP/IPTC fields.

## 2. Strings sweep

```bash
strings -n 8 -e l <file> | grep -iE 'flag|ctf|key|pass'
strings -n 8 -e b <file> | grep -iE 'flag|ctf'   # big-endian wide chars
```

## 3. Binwalk

```bash
binwalk <file>             # list embedded
binwalk -e <file>          # extract
# Then recurse on extracted contents.
```
Look for embedded ZIPs, PNGs, PDFs inside the carrier.

## 4. Appended data

Images often have data appended past the official end marker:
```bash
# PNG: IEND marker is "49 45 4e 44 ae 42 60 82"
# JPG: ends with "ff d9"
# Extract everything after:
python3 -c "
d = open('img.png','rb').read()
idx = d.rfind(b'\x49\x45\x4e\x44\xaeB\x60\x82')
open('tail.bin','wb').write(d[idx+8:])
"
```

## 5. LSB

```bash
zsteg <png>                # automatic multi-channel LSB for PNG/BMP
zsteg -a <png>             # try all permutations
```
For JPG, LSB doesn't work directly (lossy). Try:
```bash
steghide extract -sf <jpg>        # prompts for password — try blank, filename, obvious guesses
```
Custom LSB: `exploits/forensics/lsb_extract.py`.

## 6. Visual / spectral (audio + images)

- Images: load in GIMP, flip channels. Or `stegsolve`.
- Audio: open in Sonic Visualiser → add spectrogram layer. Text often appears visually.
- Alternative: `sox input.wav -n spectrogram -o out.png`

## 7. Filesystem slack (disk/memory)

```bash
file <img>                       # is it a disk image? partition table?
mmls <img>                       # sleuthkit partitions
fls -r <img>                     # file listing including deleted
icat <img> <inum> > recovered    # recover a specific inode
```

## 8. Common encodings to try on any suspicious blob

```python
import base64, zlib, bz2, gzip
for fn in [lambda b: base64.b64decode(b+b'=='),
           lambda b: base64.b32decode(b),
           lambda b: base64.b85decode(b),
           lambda b: bytes.fromhex(b.decode()),
           lambda b: zlib.decompress(b),
           lambda b: bz2.decompress(b),
           lambda b: gzip.decompress(b)]:
    try: print(fn(blob))
    except Exception: pass
```

## When all else fails

- Google the filename / exact strings — previous writeups may exist.
- Check tail vs head byte statistics (entropy) — encrypted vs encoded vs random.
- Try XOR with filename, challenge name, or obvious keys.
