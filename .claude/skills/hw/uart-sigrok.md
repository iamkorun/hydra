# Decoding UART / SPI / I2C from a Saleae .sal capture

When a challenge ships a `.sal` (Saleae Logic 2) capture — typically
UART boot logs for hardware challenges — use `sigrok-cli` with its
built-in protocol decoders. Manual binary parsing of the Saleae format
burns tokens fast and OOM-kills the container.

## The .sal format, briefly

A `.sal` is a zip archive:

```
meta.json          # sample_rate, channel layout, start/end timestamps
digital_0.bin      # packed uint8 bits of channel 0 (LSB-first)
digital_1.bin      # channel 1 if multi-channel
...
```

## The fast path (one-liner unpack + baud sweep)

`sal2sigrok` is pre-installed in the image. It unzips the archive,
unpacks each `digital_N.bin` into one-byte-per-sample, and prints the
sigrok-cli command to decode UART across common bauds.

```bash
sal2sigrok hw_debug.sal ./decoded
# The script's output includes a ready-to-paste loop. Run it:
for baud in 9600 19200 38400 57600 115200 230400 460800 921600; do
    echo "=== $baud ==="
    sigrok-cli --input-format binary:numchannels=1:samplerate=$(cat ./decoded/samplerate.txt) \
               --input-file ./decoded/channel_0.u8 \
               --protocol-decoders uart:baudrate=$baud:rx=0 \
               --protocol-decoder-annotations uart=rx-data 2>&1 | head -40
done | tee decoded.log

# Flag is usually in the boot banner. Grep it out:
grep -oE 'HTB\{[^}]+\}|flag\{[^}]+\}' decoded.log
```

The correct baud produces coherent ASCII (boot banners, `login:`,
`#`, kernel messages). Wrong bauds produce garbage bytes. Scan for
flag patterns in the decoded output.

## SPI / I2C variants

Same pipeline, different `--protocol-decoders`:

```bash
# SPI: clock on ch0, MOSI on ch1, MISO on ch2
sigrok-cli ... --protocol-decoders spi:clk=0:mosi=1:miso=2 \
               --protocol-decoder-annotations spi=mosi-data,spi=miso-data

# I2C: SCL on ch0, SDA on ch1
sigrok-cli ... --protocol-decoders i2c:scl=0:sda=1 \
               --protocol-decoder-annotations i2c=data
```

Multi-channel `.sal` files auto-unpack into `channel_0.u8`,
`channel_1.u8`, etc. Pass `binary:numchannels=N` and concatenate or
interleave the files as `sigrok-cli` expects.

## Token budget

- Unzip + meta.json + unpack: 1 tool call (`sal2sigrok <src> <out>`).
- Baud sweep across 8 rates: 1 tool call (the for-loop).
- Grep decoded output: 1 tool call.

Total: ~3 tool calls end-to-end. If you're on call 20 still manually
indexing bits in Python, stop and run `sal2sigrok`.
