# Reverse Engineering Methodology

A repeatable workflow for any rev challenge. Layers from cheap to expensive —
always go through the earlier layers before reaching for the later ones.
Adapted from CAI's reverse engineering agent (arxiv 2504.06017), tightened
for CTF jeopardy.

## Layer 0 — Identify what you have

```bash
file ./challenge/*              # architecture, packed?, bundle format
stat ./challenge/*              # size (tiny = script; huge = bundle/image)
xxd ./challenge/<bin> | head    # magic bytes; compare against `file` output
```

If `file` says `data` or is ambiguous: check magic bytes manually. Common
surprises: PyInstaller (PYZ magic), .NET (MZ + CLR), UPX (UPX! magic), raw
firmware image, or a filesystem image (squashfs/ext4) disguised as a binary.

## Layer 1 — Free flag detection

```bash
strings -a -n 8 ./challenge/<bin> | grep -iE 'flag|ctf|correct|success|wrong|{'
```

A surprising fraction of "rev" challenges hide the flag as a plain string.
Also grep for:
- `flag\{` or the competition's specific prefix
- error messages like `Wrong!` or `Access denied` — their xrefs point to the
  check function
- `strcmp`, `memcmp` — call sites often have the expected value in a
  register or nearby constant

## Layer 2 — Dynamic observation

```bash
ltrace ./challenge/<bin> <<<'test'      # libc calls (strcmp, memcmp, open)
strace -e trace=read,write,openat ./challenge/<bin> <<<'test'
./challenge/<bin> AAAAAAAA              # does it crash? where?
```

`ltrace` is extraordinarily fast at revealing the check. If you see
`strcmp("AAAAAAAA", "real_password_here")`, you're done.

## Layer 3 — Disassembly triage with r2

```bash
r2 -A -q -c 'afl ; s main ; pdf' ./challenge/<bin>   # auto-analyze + list funcs + main
```

Useful r2 commands for quick triage:
- `afl`                   — list functions
- `axt @ sym.strcmp`      — xrefs to strcmp
- `izz | grep flag`       — search strings across whole binary
- `pdf @ main`            — print disassembly of main
- `s sym.<name> ; pdf`    — seek to function, print

For anything more than triage, switch to Ghidra headless.

## Layer 4 — Ghidra headless decompilation

```bash
mkdir -p ./work/ghidra_proj
analyzeHeadless ./work/ghidra_proj myproj \
  -import ./challenge/<bin> \
  -postScript ~/ghidra_scripts/DecompileAll.java \
  -scriptPath ~/ghidra_scripts
```

Writes `.java`-like decompilation to the script's output path. Read `main`,
then check functions. Look for: obvious xor loops, simple substitution,
arithmetic transforms on the input buffer, single-byte comparisons (FLAG
byte-at-a-time oracle).

## Layer 5 — Symbolic execution with angr

When the check is a real algorithm (not just `strcmp`), try angr before
hand-reversing:

```python
# See exploits/pwn/angr_find_input.py (works for rev too).
import angr
proj = angr.Project('./challenge/<bin>', auto_load_libs=False)
sm = proj.factory.simulation_manager(proj.factory.entry_state())
sm.explore(find=WIN_ADDR, avoid=FAIL_ADDR)
if sm.found:
    print(sm.found[0].posix.dumps(0))     # flag input
```

State explosion warnings: if angr hangs, narrow with `stashes`, add hooks
to skip expensive opaque functions, or use `claripy` constraints directly.

## Layer 6 — Patch instead of reverse

If the check is a single `jne`/`jz`, patch it:

```bash
# Example: flip a conditional jump at 0x401234 from "jne" (0x75) to "je" (0x74)
r2 -qwc 'wx 74 @ 0x401234' ./challenge/<bin>
./challenge/<bin> anything       # now takes anything
```

For multi-byte patches, `radare2` `wa` (assemble in place) or `objcopy` with
a custom script.

## Non-x86 / non-native binaries

| Format | Tool chain |
|---|---|
| PyInstaller | `pyinstxtractor-ng <bundle>` → get `.pyc` → `uncompyle6` or `decompyle3` |
| Python `.pyc` (3.9+) | `uncompyle6` fails; use `decompile3` or read bytecode with `dis` |
| Java JAR / APK | `jadx -d out_dir ./challenge.jar` (or `.apk`) |
| .NET | `strings` first, then `ilspycmd` / `dnSpy` (not pre-installed — `apt install mono-devel` + `ilspy` or use online) |
| WASM | `wasm-decompile ./challenge.wasm` (binaryen package) |
| Go (stripped) | `strings` + `radare2` `aaaa`; symbols often recoverable from Go metadata |
| Rust | Symbols are there but mangled; `rustfilt` or r2's demangler |
| UPX-packed | `upx -d ./bin` ; if custom packer, see Layer 4 |

## One-shot commands only

**Never use interactive commands.** Hydra runs inside a container; the
specialist can't ctrl-c out of an interactive session.
- Bad: `gdb ./bin`
- Good: `gdb -batch -ex 'disas main' ./bin`
- Bad: `r2 ./bin`
- Good: `r2 -qc 'afl; pdf@main' ./bin`
- Bad: `python3 -i exploit.py`
- Good: `python3 exploit.py`

If you truly need a persistent session (e.g., gdb with breakpoints that
depend on earlier state), use the tmux pattern: `.claude/skills/pwn/tmux-session.md`.

## Stop conditions

- Flag recovered → done.
- 8 failed attempts at a single layer → drop to the next layer or pivot to a
  different approach.
- If Layers 0-3 all empty-handed and the binary is clearly doing something
  non-trivial, escalate to decompilation or angr rather than continuing
  hand-analysis.

## Reference

- **CAI** (arxiv 2504.06017): `src/cai/prompts/reverse_engineering_agent.md`
  — base methodology.
- **Palisade** (arxiv 2412.02776): plain ReAct + `strings`/`ltrace` is
  surprisingly competitive on rev.
- **EnIGMA** (arxiv 2409.16165): for truly interactive rev work (watchpoints,
  step-through), see the tmux IAT pattern.
