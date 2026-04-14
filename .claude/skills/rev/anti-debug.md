# Anti-Debug / Anti-Analysis Bypass

Modern rev challenges increasingly ship with anti-debug: the binary detects gdb /
ltrace / ptrace / a mounted `/proc`, and either crashes, prints garbage, corrupts
the flag check, or refuses to decrypt the real flag. Treat these as deterministic
checks — find them, bypass them, move on. The moment a binary refuses to run
under gdb or produces a wrong-looking output that changes when you attach a
debugger, reach for this skill. Audit of Hydra's rev corpus says ~30% of
medium+ challenges have at least one anti-debug technique stacked on the real
algorithm.

The workflow is strictly layered: detect → static patch → runtime bypass → symex.
Do not jump to angr before you have grepped strings.

## Layer 0 — Detect the check

Every anti-debug technique leaves a fingerprint. Before anything else:

```bash
# Strings: 90% of checks show up here.
strings -a ./challenge/bin | grep -iE 'ptrace|tracerpid|/proc/self|ld_preload|ld_audit|vmware|vbox|qemu|hypervisor|rdtsc|int3|sigtrap|getenv|getppid'

# ltrace: catches libc-level checks (getenv, ptrace, getppid, open).
ltrace -f -o /tmp/lt.log ./challenge/bin <<<"test"
grep -E 'ptrace|getenv|getppid|open.*/proc' /tmp/lt.log

# strace: catches raw syscalls (ptrace syscall 101 on x86_64, openat on /proc).
strace -f -o /tmp/st.log -e trace=ptrace,openat,prctl,getppid,rt_sigaction ./challenge/bin <<<"test"

# Baseline: run without debugger, save stdout.
./challenge/bin <<<"test" > /tmp/normal.out 2>&1

# Compare under gdb: anything that differs is anti-debug-triggered.
gdb -batch -ex 'run <<<"test"' ./challenge/bin > /tmp/gdb.out 2>&1
diff /tmp/normal.out /tmp/gdb.out
```

If the strings grep returns nothing *and* the binary runs the same under gdb,
there is no anti-debug — skip to `rev-methodology.md`.

Xrefs to anti-debug primitives with r2:

```bash
r2 -A -q -c 'axt @ sym.ptrace ; axt @ sym.imp.ptrace' ./challenge/bin
r2 -A -q -c 'axt @ sym.getenv' ./challenge/bin
r2 -A -q -c '/ ptrace' ./challenge/bin           # textual search in mapped code
r2 -A -q -c '/x 0f31' ./challenge/bin            # rdtsc bytes
```

## Layer 1 — Static patch (fastest)

Cheapest win: patch the check out of the binary once, save, run freely.

### radare2 one-liners

```bash
# Nop out one instruction at 0x401234.
r2 -qwc 's 0x401234 ; wa nop' ./challenge/bin

# Flip jne (0x75) → je (0x74) at the check site.
r2 -qwc 'wx 74 @ 0x401234' ./challenge/bin

# Stub a whole function: return 0 immediately.
r2 -qwc 'wa mov eax, 0 ; ret @ sym.anti_debug' ./challenge/bin

# Replace a call target: rewrite "call sym.check" with nops (5 bytes on x86_64 near-call).
r2 -qwc 'wx 9090909090 @ 0x401240' ./challenge/bin
```

Always copy first. Patching is destructive:

```bash
cp ./challenge/bin ./work/bin.patched
r2 -qwc '...' ./work/bin.patched
```

### LIEF for structured patches

For multi-site patches or when you want idempotent Python:

```python
import lief
bin = lief.parse('./challenge/bin')
# 4-byte nop at 0x401234
bin.patch_address(0x401234, [0x90, 0x90, 0x90, 0x90])
# Replace a whole function with "xor eax, eax ; ret"
bin.patch_address(0x401500, [0x31, 0xc0, 0xc3])
bin.write('./work/bin.patched')
```

Then `chmod +x ./work/bin.patched` and run.

### patchelf — for loader / rpath tricks

If the check depends on dynamic linker behavior (e.g., the binary refuses to run
against non-default libc because of version mismatch):

```bash
patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 ./work/bin.patched
patchelf --set-rpath '$ORIGIN' ./work/bin.patched
```

## Layer 2 — Runtime bypass

When static patching is risky (checksummed `.text`, packed code, many call
sites) bypass at runtime.

### LD_PRELOAD shim — intercept libc

The canonical tool. Compile a tiny `.so` that overrides `ptrace`, `getenv`,
`open`, `ptrace`, etc.

```c
// shim.c
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/ptrace.h>
#include <dlfcn.h>

// Pretend ptrace always succeeds.
long ptrace(int req, pid_t pid, void *addr, void *data) { return 0; }

// Hide LD_PRELOAD / LD_AUDIT from the victim.
char *getenv(const char *name) {
    if (!strcmp(name, "LD_PRELOAD") || !strcmp(name, "LD_AUDIT")) return NULL;
    static char *(*real)(const char *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "getenv");
    return real(name);
}

// Fake TracerPid when the binary reads /proc/self/status.
int open(const char *path, int flags, ...) {
    static int (*real)(const char *, int, ...) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "open");
    if (path && strstr(path, "/proc/self/status")) {
        // Serve a fake status file with TracerPid: 0.
        FILE *f = tmpfile();
        fputs("Name:\tbin\nState:\tR (running)\nTracerPid:\t0\n", f);
        rewind(f);
        return fileno(f);
    }
    return real(path, flags);
}

// getppid — pretend we are child of init.
pid_t getppid(void) { return 1; }
```

```bash
gcc -shared -fPIC -o /tmp/shim.so shim.c -ldl
LD_PRELOAD=/tmp/shim.so ./challenge/bin
```

Keep the shim minimal. Add only the interceptors needed for *this* binary.

### gdb scripts — catch syscalls, reset registers

When the binary uses the raw `ptrace` syscall (bypassing libc) or reads rdtsc:

```python
# /tmp/bypass.gdb
# Force ptrace syscall to return 0.
catch syscall ptrace
commands
    set $rax = 0
    continue
end

# Reset rdtsc result so two reads are always "fast".
catch signal SIGSEGV
break *&rdtsc_call_site
commands
    set $rdx = 0
    set $rax = 0x1000
    continue
end

run
```

```bash
gdb -batch -x /tmp/bypass.gdb ./challenge/bin
```

Use hardware breakpoints when the binary checksums its own `.text`:

```
(gdb) hbreak *0x401234      # hw breakpoint (DR0-DR3), max 4
```

Software breakpoints (`b`) write `0xCC` into `.text` and break self-checksums.

### Clear environment to bypass env-var poisoning

```bash
env -i PATH=/usr/bin:/bin ./challenge/bin
```

Combine with `setsid` / `nohup` if the binary checks parent pid:

```bash
setsid ./challenge/bin </dev/null     # new session, ppid = 1-ish
nohup ./challenge/bin &
```

## Layer 3 — Symbolic execution / emulation (last resort)

When the anti-debug is multi-layered, self-modifying, or calls into opaque code
you don't want to fully reverse, stub it out with symbolic execution.

### angr: hook the check to always return success

```python
import angr, claripy
proj = angr.Project('./challenge/bin', auto_load_libs=False)

# Hook the anti-debug function: replace with a no-op that returns 0.
proj.hook_symbol('is_debugged', angr.SIM_PROCEDURES['stubs']['Nop']())
proj.hook_symbol('ptrace',      angr.SIM_PROCEDURES['stubs']['ReturnUnconstrained']())

# If the function isn't a symbol, hook by address.
proj.hook(0x401500, angr.SIM_PROCEDURES['stubs']['Nop'](), length=5)

input_ = claripy.BVS('input', 32 * 8)
state  = proj.factory.entry_state(stdin=input_)
sm = proj.factory.simulation_manager(state)
sm.explore(find=WIN_ADDR, avoid=FAIL_ADDR)
if sm.found:
    print(sm.found[0].posix.dumps(0))
```

`stubs.Nop` is the "do absolutely nothing" SimProcedure; `ReturnUnconstrained`
lets angr pick a concrete return value that reaches the goal.

### Qiling — full-system emulation with hooks

Install on demand:

```bash
pip install --user qiling
```

Qiling emulates the full OS syscall surface, so `ptrace` / `/proc` reads return
whatever you script:

```python
from qiling import Qiling
ql = Qiling(['./challenge/bin'], '/path/to/rootfs/x8664_linux')

# Hook ptrace syscall: always return 0.
def fake_ptrace(ql, *args):
    return 0
ql.os.set_syscall('ptrace', fake_ptrace)

ql.run()
```

Docs: https://github.com/qilingframework/qiling

### unicorn — raw CPU emulation

When you only care about the algorithm inside a single function and don't want
any OS interference:

```python
from unicorn import *
from unicorn.x86_const import *
mu = Uc(UC_ARCH_X86, UC_MODE_64)
mu.mem_map(0x400000, 2*1024*1024)
mu.mem_write(0x400000, open('./challenge/bin', 'rb').read())
mu.reg_write(UC_X86_REG_RIP, 0x4013a0)
mu.emu_start(0x4013a0, 0x4013ff)
print(hex(mu.reg_read(UC_X86_REG_RAX)))
```

No OS → no anti-debug check to trigger. Downside: you set up all memory /
registers by hand.

---

## Per-technique catalog

Each technique: signature (how to detect), bypass (what to do).

### 1. `ptrace(PTRACE_TRACEME)` — the classic

The binary calls `ptrace(PTRACE_TRACEME, 0, 0, 0)` early. If another process is
already attached (i.e., gdb), the call returns -1.

**Signature:**

```bash
strings ./challenge/bin | grep -i ptrace
ltrace ./challenge/bin 2>&1 | grep ptrace
# Or disassemble:
r2 -A -q -c 'axt @ sym.imp.ptrace' ./challenge/bin
# Raw syscall (no libc):
r2 -A -q -c '/x b83f000000' ./challenge/bin   # mov eax, 0x65 (ptrace syscall)
```

**Bypass:**

- Patch: nop the `call ptrace` (5 bytes on x86_64).
- LD_PRELOAD shim (above) — `long ptrace(...) { return 0; }`.
- gdb: `catch syscall ptrace` + `set $rax = 0 ; continue`.

### 2. `/proc/self/status` TracerPid check

The binary opens `/proc/self/status`, parses `TracerPid:` line, and if non-zero
concludes it's being traced.

**Signature:**

```bash
strings ./challenge/bin | grep -E 'TracerPid|/proc/self/status|/proc/self/stat'
strace -e trace=openat ./challenge/bin 2>&1 | grep proc
```

**Bypass:**

- LD_PRELOAD the `open`/`openat` call (above) to serve a fake file with
  `TracerPid: 0`.
- Bind-mount a fake file (requires `CAP_SYS_ADMIN` or rootless mount ns):
  ```bash
  echo -e "Name:\tbin\nTracerPid:\t0" > /tmp/fake_status
  unshare -m --map-root-user sh -c 'mount --bind /tmp/fake_status /proc/self/status ; ./bin'
  ```
- Patch the strncmp on `"TracerPid"`.

### 3. RDTSC timing check

Two `rdtsc` instructions bracketing the interesting code; a threshold means
"under debugger."

**Signature:**

```bash
r2 -A -q -c '/x 0f31' ./challenge/bin        # rdtsc = 0x0f 0x31
```

Usually you'll see two hits close together plus a `sub` / `cmp`.

**Bypass:**

- Patch the `cmp` threshold so the check is always false.
- gdb script: at each rdtsc site, `set $rdx = 0 ; set $rax = 0` — force
  constant time.
- Set CPU `cr4.TSD` via kernel module (overkill; almost never needed in CTF).
- Simplest: patch both `rdtsc` to `xor edx, edx ; xor eax, eax` (same length:
  2 bytes each; pad with `nop`).

### 4. INT3 detection / self-checksum

The binary walks its own `.text` section, computes a hash, bails if it doesn't
match the expected. A `gdb` software breakpoint writes `0xCC` → corrupts hash.

**Signature:**

```bash
# The binary reads its own maps, or the address range corresponds to .text.
strings ./challenge/bin | grep -E '/proc/self/maps|/proc/self/mem'
# Ghidra: look for loops that read from .text and fold via xor/sha/sum.
```

**Bypass:**

- Hardware breakpoints only: `hbreak *0x401234`. Max 4 simultaneous (DR0-DR3).
- Patch the checksum comparison to always succeed.
- Run the binary, grab a stdout trace, reverse statically — don't attach at all.

### 5. SIGTRAP handler hijacking

The binary installs its own `SIGTRAP` handler via `sigaction`. When an `INT3`
fires, *the real decryption / flag logic runs inside the handler.* A debugger
catches the `SIGTRAP` first and executes the "wrong" path (normal flow).

**Signature:**

```bash
ltrace ./challenge/bin 2>&1 | grep -E 'sigaction|signal'
strace -e trace=rt_sigaction ./challenge/bin
```

Ghidra: search for `sigaction(SIGTRAP, ...)` then read the handler.

**Bypass:**

- In gdb: `handle SIGTRAP noprint nostop pass` — let the signal through to the
  handler. Combine with hw breakpoints outside the INT3 trap site.
- Patch the INT3 to an unconditional branch to the real handler's body.
- Symex: hook the handler, have angr execute both sides explicitly.

### 6. Env-var poisoning (`LD_PRELOAD`, `LD_AUDIT`)

Binary calls `getenv("LD_PRELOAD")` and refuses if non-null. A self-defense
against shims.

**Signature:**

```bash
ltrace ./challenge/bin 2>&1 | grep 'getenv.*LD_'
strings ./challenge/bin | grep -E 'LD_PRELOAD|LD_AUDIT|LD_DEBUG'
```

**Bypass:**

- `env -i ./challenge/bin` — clean env.
- Shim `getenv` to return NULL for those names (see Layer 2 shim).
- Patch the `getenv` call + comparison.

### 7. Parent-PID / session check

Binary calls `getppid()` and compares against 1 (init) or against the pid of
`gdb`.

**Signature:**

```bash
ltrace ./challenge/bin 2>&1 | grep getppid
```

Or in disassembly: `call getppid` followed by `cmp eax, 1`.

**Bypass:**

- `setsid ./challenge/bin </dev/null >&0 2>&0` — new session; ppid typically
  becomes 1.
- `nohup ./challenge/bin &` then attach gdb after the fact (`gdb -p <pid>`).
- Shim `getppid` to return 1.
- Patch the `cmp`.

### 8. Syscall-timing under ptrace

Each syscall under ptrace fires a ptrace stop → huge overhead. Binary measures
e.g. 100 `getpid()` calls; if they take too long, flag as debugged.

**Signature:** `rdtsc` surrounding a tight syscall loop.

**Bypass:**

- Don't single-step. Use function-level breakpoints.
- gdb: `catch syscall` + `pass` mode lets syscalls through without slow
  stops (not always reliable — prefer patch).
- Patch the threshold.

### 9. Kernel / VM detection

Binary opens `/proc/modules`, `/sys/class/dmi/id/product_name`, or issues
`cpuid` leaf `0x40000000` (hypervisor vendor). If it sees `vmware`, `vbox`,
`kvm`, `qemu`, it bails.

**Signature:**

```bash
strings ./challenge/bin | grep -iE 'vmware|vbox|kvm|qemu|hypervisor|vmguest|xen'
r2 -A -q -c '/x 0fa2' ./challenge/bin   # cpuid opcode
```

**Bypass:**

- Patch the check.
- LD_PRELOAD shim for `open` on `/proc/modules` / `/sys/...`.
- Run on bare-metal host (if container allows it).
- gdb: breakpoint the cpuid result, `set $eax = 0x756e6547` etc.

### 10. `.plt` / `.got` integrity check

Binary hashes its own PLT entries at startup, then again before the flag check,
and bails on mismatch. Defeats LD_PRELOAD-style hooking (PLT gets rewritten).

**Signature:** loop that reads the ELF's PLT / GOT range and folds into a hash.

**Bypass:**

- Use LD_PRELOAD with `LD_BIND_NOW=1` *and* a shim that doesn't modify GOT
  (some shims are transparent; test first).
- Work at the function level, not via libc hooking — patch the target function
  in place with radare2.
- Keep debugging scoped to user code (not PLT jumps).

### 11. Stack canary / guard check

Some binaries compute SHA over a stack region or check register invariants.
Single-stepping clobbers scratch state (e.g. `TF` flag visible in `eflags` on
stack).

**Signature:** SHA constants (`0x67452301`, `0xefcdab89`, etc.) in `.rodata` +
a read of `rsp`-relative memory that isn't a local var.

**Bypass:**

- Don't single-step through the guarded function. Breakpoint at the start and
  end; read state without stepping.
- Patch the guard.

### 12. Anti-dump / argv[0] / inode checks

Binary checks `argv[0]` equals `/opt/chal/bin` or `stat()`s itself and checks
inode / size. Defeats copy-then-patch.

**Signature:**

```bash
strings ./challenge/bin | grep -E '^/opt/|^/usr/local/|argv\[0\]'
strace ./challenge/bin | grep stat
```

**Bypass:**

- Run under the expected name: `exec -a /opt/chal/bin ./work/bin.patched`.
- Keep the binary at the expected path and patch in place.
- Shim `stat` / `lstat` to return the expected size/inode.
- Patch the inode/size comparison.

### 13. Anti-hook / runtime dlsym lookup

Binary does its own `dlopen("libc.so.6") ; dlsym(h, "ptrace")` at runtime,
avoiding PLT. LD_PRELOAD shims of specific symbols don't intercept this —
`dlsym` resolves directly to the real libc symbol.

**Signature:** `dlopen` / `dlsym` calls in the binary, often with `libc`
string constants.

**Bypass:**

- Shim `dlsym` itself: if the requested name is `ptrace`, return your fake.
- Patch the `dlsym` call to a fixed target.
- Symex: hook `dlsym` in angr to return a stub.

## Anti-debug stacking

Medium+ challenges often stack 3-5 of the above. Kill them in the order the
binary triggers them, which is usually chronological from `_start`:

1. `ptrace(PTRACE_TRACEME)` in `.init_array` or early `main`.
2. Env-var check (`LD_PRELOAD`, `LD_AUDIT`).
3. `/proc/self/status` TracerPid.
4. Parent-pid / session check.
5. RDTSC timing around the flag check itself.
6. Self-checksum before the decryption routine.
7. SIGTRAP-hijack for the flag-decrypt logic.

Workflow:

```bash
# Iteration loop:
cp ./challenge/bin ./work/bin.v1
ltrace -f ./work/bin.v1 2>&1 | head -100
# Identify the first offending check.
r2 -qwc 'wx 9090...' ./work/bin.v1        # patch it out
./work/bin.v1                              # does it run further now?
# Repeat for each layer.
```

Each iteration should move strictly further through the binary's control flow.
If a patch makes *less* progress than the previous version, you patched the
wrong thing or broke a side-effect (e.g., a check that also set up state).

## Self-modifying / packed binaries

Cross-ref `rev-methodology.md` Layer 2 on unpacking.

```bash
# UPX: easy, just -d.
upx -d ./challenge/bin
# Verify: strings should look like a normal binary afterwards.
strings ./challenge/bin | head -50
```

For custom packers (no `UPX!` magic, no known signature):

```bash
# Catch mprotect + memcpy during unpack.
ltrace -e 'mprotect+memcpy+memmove' ./challenge/bin
# When unpack is done (usually after mprotect flips RWX→RX), dump memory.
gdb -batch \
    -ex 'b mprotect' \
    -ex 'commands' -ex 'if $rdx == 5' -ex 'dump memory /tmp/unpacked.bin $rdi $rdi+$rsi' -ex 'end' -ex 'continue' -ex 'end' \
    -ex 'run' ./challenge/bin
# Analyze the dumped region with r2 / Ghidra.
r2 /tmp/unpacked.bin
```

Self-modifying code that writes `.text` on the fly: hw breakpoints only; the
JIT-like writes corrupt software breakpoints.

## Common traps

- **The check is in `.init_array`** and runs *before* `main`. Your `b main`
  breakpoint is too late. Use `starti` in gdb (stop at `_start`) and step from
  there, or set a breakpoint at the `.init_array` entry.
- **SIGTRAP handler doubles as the real code path.** If you set `handle SIGTRAP
  stop` you'll miss the flag-decrypt. Set to `nostop pass`.
- **Self-checksum runs twice** — once early, once before flag output. Patching
  the first one isn't enough.
- **`ptrace(PTRACE_TRACEME)` twice** — some binaries call TRACEME in both a
  parent and a fork()'d child. Shim must return 0 unconditionally.
- **Env-var check also validates absence of `COLUMNS` / `LINES`** (weird, but
  seen in the wild). `env -i` is safer than patching individual names.
- **Patched binary runs, but flag is garbage.** You bypassed the *detection*
  but not the *consequence* — the detection probably XORs a key. Find the XOR
  side-effect and suppress it too, not just the branch.
- **Timing check with `clock_gettime` instead of rdtsc.** Grep covers both but
  don't assume rdtsc is the only source.

## Tools in Hydra image

- `gdb` (add pwndbg/GEF on demand: `pip install pwndbg` or clone GEF)
- `radare2` + r2pipe (pip: `r2pipe`)
- `ghidra` — `analyzeHeadless` for scripted decomp
- `ltrace`, `strace`
- `angr` (already present via rev dependencies)
- `patchelf`
- `LIEF` (pip — usually present via pwntools)
- `upx`
- `binaryen` / `wasm-decompile` (for wasm targets)

## Install on demand

```bash
pip install --user qiling          # full-system emulator with bypass hooks
pip install --user unicorn         # raw CPU emulation
git clone https://github.com/pwndbg/pwndbg /tmp/pwndbg && /tmp/pwndbg/setup.sh
git clone https://github.com/bata24/gef /tmp/gef                  # active GEF fork
git clone https://github.com/extremecoders-re/anti-debug /tmp/ad  # reference binaries
```

## References

- https://github.com/extremecoders-re/anti-debug — canonical Linux anti-debug
  catalog; test harness for each technique.
- https://anti-debug.checkpoint.com/ — Windows-focused; many primitives
  (RDTSC, self-checksum, SIGTRAP / SEH) carry over.
- https://ired.team/offensive-security/code-injection-process-injection —
  dynamic-analysis bypass techniques.
- https://ropemporium.com/ — pwn-oriented but shares the "patch rather than
  reverse" instinct.
- Qiling: https://github.com/qilingframework/qiling
- Unicorn: https://github.com/unicorn-engine/unicorn
- angr hooks: https://docs.angr.io/en/latest/core-concepts/simulation.html
- Palisade (arxiv 2412.02776): try `strings` + `ltrace` before assuming
  anti-debug. Most "spooky" binaries have an obvious getenv call first.
- EnIGMA (arxiv 2409.16165): IAT pattern for long-running gdb sessions —
  mandatory when you need more than two breakpoints.

## Stop conditions

Pivot away from dynamic bypass when:

- **Three+ layers stacked** and each new patch breaks a side-effect. At that
  point the binary is fighting you faster than you can patch. Drop to Ghidra
  headless, read the algorithm, reimplement it in Python, skip execution
  entirely.
- **Self-modifying code you can't snapshot** (mprotect-then-run inside
  encrypted segment). Use Qiling or unicorn to emulate; if that fails, read
  statically.
- **Checksum over a moving window including the check itself.** These are
  usually solvable by computing the expected hash *externally* and patching
  the compared constant (not the check).
- **You've spent 45+ minutes on bypass and the check algorithm looks like a
  clean KSA/xor/feistel.** Reimplement the algorithm and skip the runtime.
- **angr hangs state-exploded even with hooks.** Narrow to one function with
  unicorn, or hand-reverse.

In all these cases, the escape hatch is the same: *the binary's output is a
deterministic function of its input.* If you can read the function statically,
you don't need to run it.
