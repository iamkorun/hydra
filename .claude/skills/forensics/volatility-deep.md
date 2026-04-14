# Volatility Memory Forensics — Deep Workflow

Memory dumps are one of the highest-yield forensics categories, and also one
where a specialist can burn an hour running the wrong plugins. This skill
gives you a plugin chain that covers the common flag-hiding spots on both
Windows and Linux in a predictable order.

Hydra ships `volatility3` (pip-installed). Check with `vol.py --help` or
`python3 -m volatility3 --help`.

## Step 0 — Identify the dump

```bash
file ./challenge/*.dmp ./challenge/*.raw ./challenge/*.vmem ./challenge/*.mem
```

Expected output:
- `DOS/MBR boot sector` or `data` — raw memory dump (most common)
- `VMware4 disk image` — `.vmem` from VMware
- `EWF/Expert Witness Compression Format` — `.E01` — mount first

Volatility3 auto-detects the OS; you do **not** need a profile (that was
Volatility2). If vol3 fails, the dump is probably truncated.

## Step 1 — Metadata & sanity

```bash
vol -f ./challenge/dump.mem windows.info       # or linux.info / mac.info
```

Note the `NtMajorVersion`, `NtMinorVersion`, and `NtBuildNumber`. If this
command errors with "No valid symbols", vol3 can't identify the kernel —
the dump may be partial or the symbol table is missing. Grab matching
symbols from https://github.com/volatilityfoundation/volatility3/tree/stable/volatility3/framework/symbols/windows
(or linux/) and drop into `symbols/`.

## Step 2 — Process universe

```bash
vol -f dump.mem windows.pslist > ./work/pslist.txt
vol -f dump.mem windows.pstree > ./work/pstree.txt
vol -f dump.mem windows.psscan  > ./work/psscan.txt   # finds hidden/exited
```

Diff `pslist` vs `psscan` — processes only in `psscan` are hidden or exited.
Those are almost always suspicious.

**For each suspicious PID**, note parent-child relationships. Common red
flags: `cmd.exe` spawned from `svchost.exe`, `powershell.exe` from a
non-`explorer.exe` parent.

### Linux equivalent

```bash
vol -f dump.mem linux.pslist.PsList
vol -f dump.mem linux.bash.Bash       # bash history — enormous wins here
vol -f dump.mem linux.psscan.PsScan   # process hiding
```

`linux.bash.Bash` is the #1 highest-ROI Linux memory plugin — bash command
history often has the flag, a password, or a URL leading to the flag.

## Step 3 — Command lines, DLLs, handles

```bash
vol -f dump.mem windows.cmdline > ./work/cmdline.txt
vol -f dump.mem windows.cmdscan > ./work/cmdscan.txt   # console command history
vol -f dump.mem windows.consoles
vol -f dump.mem windows.dlllist --pid <PID>
vol -f dump.mem windows.handles --pid <PID>
```

`cmdscan` and `consoles` read the command history out of `conhost.exe` /
`csrss.exe` memory — they find commands a user typed interactively.

## Step 4 — Files

```bash
vol -f dump.mem windows.filescan > ./work/filescan.txt
# Dump a specific file by its virtual address:
vol -f dump.mem windows.dumpfiles --virtaddr 0xfffffa8000abc123 -o ./work/
# Dump all files matching a regex:
vol -f dump.mem windows.dumpfiles --filter "flag|ctf|secret"
```

`filescan` gives you the virtual addresses; feed one to `dumpfiles`.

## Step 5 — Credentials & secrets

```bash
vol -f dump.mem windows.hashdump       # SAM/SYSTEM password hashes
vol -f dump.mem windows.lsadump        # LSA secrets (cached credentials)
vol -f dump.mem windows.cachedump      # domain cached credentials
vol -f dump.mem windows.netscan        # TCP/UDP connections, may reveal C2
```

Hashes are usable with `hashcat -m 1000 <NTLM>` (not yet installed — if a
chal needs it, `apt install hashcat` ad-hoc in `./work/`).

## Step 6 — Network

```bash
vol -f dump.mem windows.netscan > ./work/netscan.txt
vol -f dump.mem windows.netstat  > ./work/netstat.txt
```

Look for: unexpected outbound connections, RDP (3389), SMB (445), reverse
shells on high ports. Pair each connection with its owning PID from Step 2.

## Step 7 — Malicious code

```bash
vol -f dump.mem windows.malfind > ./work/malfind.txt     # injected code
vol -f dump.mem windows.hollowfind                       # process hollowing
vol -f dump.mem windows.modules                          # loaded drivers
vol -f dump.mem windows.modscan                          # hidden drivers
```

`malfind` dumps regions of memory marked executable + writable that don't
belong to a loaded module — high-signal for injected shellcode.

## Step 8 — Registry (Windows)

```bash
vol -f dump.mem windows.registry.hivelist
vol -f dump.mem windows.registry.printkey --key 'Software\Microsoft\Windows\CurrentVersion\Run'
vol -f dump.mem windows.registry.userassist
```

Registry keys often hold persistence mechanisms and leftover artifacts.
`userassist` records which programs the user launched — another
highest-ROI plugin when the chal implies "what did the user do".

## Step 9 — Strings (always as a last resort, always with pid filter)

```bash
strings -a -n 8 ./challenge/dump.mem | grep -iE 'flag|ctf|{[a-z0-9_]+}' | sort -u | head -50
```

Useful when targeted plugins come up empty. The flag is often in memory
even when you can't attribute it to a specific process.

## Linux-specific high-value plugins

```bash
vol -f dump.mem linux.bash.Bash           # bash history (top priority)
vol -f dump.mem linux.pslist.PsList
vol -f dump.mem linux.psaux.PsAux         # with argv — often has passwords
vol -f dump.mem linux.lsmod.Lsmod
vol -f dump.mem linux.malfind.Malfind
vol -f dump.mem linux.proc.Maps           # memory regions
```

## Recipe for a fresh dump

Run these in order and read the output between each step. Ninety percent
of memory-forensics CTFs fall to this chain:

```bash
vol -f dump.mem windows.info
vol -f dump.mem windows.pslist
vol -f dump.mem windows.pstree
vol -f dump.mem windows.cmdline
vol -f dump.mem windows.cmdscan
vol -f dump.mem windows.filescan | grep -iE 'flag|ctf|secret|\.txt$|\.docx$|\.png$'
vol -f dump.mem windows.malfind
```

If still empty:

```bash
vol -f dump.mem windows.hashdump
vol -f dump.mem windows.registry.printkey --key 'Software\Microsoft\Windows\CurrentVersion\Run'
strings -a -n 8 dump.mem | grep -iE 'flag\{|FLAG\{|CTF\{'
```

## Reference

- **CAI** (arxiv 2504.06017): `src/cai/prompts/memory_analysis_agent.md` —
  base pattern.
- Volatility3 docs: https://volatility3.readthedocs.io/
- SANS memory forensics cheat sheet: `https://www.sans.org/posters/` (look
  for "Hunt Evil" poster).
