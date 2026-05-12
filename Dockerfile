FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

# System layer (rare churn)
# fd-find installs the binary as `fdfind` on Debian/Ubuntu; symlink to `fd` for muscle memory.
COPY docker/apt-packages.txt /tmp/apt-packages.txt
RUN apt-get update \
 && xargs -a /tmp/apt-packages.txt apt-get install -y --no-install-recommends \
 && ln -s /usr/bin/fdfind /usr/local/bin/fd \
 && rm -rf /var/lib/apt/lists/*

# Python CTF stack (rare churn)
COPY docker/requirements-ctf.txt /tmp/requirements-ctf.txt
RUN pip install -r /tmp/requirements-ctf.txt \
 && pip install --no-deps pyinstxtractor-ng==2025.1.6

# Playwright Chromium for JS-heavy web challenges (~300 MB).
# --with-deps pulls apt runtime libs; must run before apt lists are cleaned.
RUN playwright install --with-deps chromium

# Specialist tooling — web + reverse + crypto + forensics.
# Consolidated into one layer: all rare-churn, single `apt-get update` cuts ~30s off rebuilds.
# - web:       ffuf gobuster sqlmap nikto wfuzz
# - reverse:   radare2 ltrace strace upx-ucl
# - crypto:    pari-gp (factoring, number theory). sagemath gone from noble — use fpylll/flatter
#              from pip, or conda ad-hoc in work/ for Coppersmith/LLL.
# - forensics: binwalk foremost steghide tshark exiftool sleuthkit (fls/icat/mmls) binaryen
#              (wasm-decompile). zsteg is a Ruby gem, installed below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ffuf gobuster sqlmap nikto wfuzz \
    radare2 ltrace strace upx-ucl \
    pari-gp \
    binwalk foremost steghide tshark exiftool sleuthkit binaryen \
 && rm -rf /var/lib/apt/lists/*

# External git-installed tools.
# RsaCtfTool pins outdated versions (pycryptodome==3.10, z3-solver, requests, chardet...)
# that would downgrade our pwntools/angr stack. Isolate it in a dedicated venv (python3-venv
# is already in the base apt layer) and wrap as a shim script so the global Python env
# stays pinned to our versions.
RUN git clone --depth 1 https://github.com/RsaCtfTool/RsaCtfTool /opt/RsaCtfTool \
 && python3 -m venv /opt/RsaCtfTool/.venv \
 && /opt/RsaCtfTool/.venv/bin/pip install --no-cache-dir -r /opt/RsaCtfTool/requirements.txt \
 && printf '#!/bin/sh\nexec /opt/RsaCtfTool/.venv/bin/python /opt/RsaCtfTool/RsaCtfTool.py "$@"\n' \
      > /usr/local/bin/RsaCtfTool \
 && chmod +x /usr/local/bin/RsaCtfTool
# Ruby gems: one_gadget (pwn libc gadget finder), zsteg (PNG/BMP LSB stego).
RUN gem install one_gadget zsteg

# Ghidra headless — NSA reverse-engineering suite. Requires JDK 21 (default-jdk-headless on noble).
# Version pinned; check `gh release view --repo NationalSecurityAgency/ghidra` to bump.
ARG GHIDRA_VERSION=12.0.4
ARG GHIDRA_DATE=20260303
RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jdk-headless \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL -o /tmp/ghidra.zip \
    "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_${GHIDRA_VERSION}_build/ghidra_${GHIDRA_VERSION}_PUBLIC_${GHIDRA_DATE}.zip" \
 && unzip -q /tmp/ghidra.zip -d /opt \
 && rm /tmp/ghidra.zip

# analyzeHeadless wrapper: caps the number of Ghidra calls per
# container to prevent the agent from burning token budget on
# re-decompilation loops.
COPY docker/ghidra-wrapper.sh /usr/local/bin/analyzeHeadless
RUN chmod +x /usr/local/bin/analyzeHeadless

# Jadx (Java decompiler) — not in Ubuntu noble apt, download from github release.
# Shares the JDK from the Ghidra layer above.
ARG JADX_VERSION=1.5.5
RUN curl -fsSL -o /tmp/jadx.zip \
    "https://github.com/skylot/jadx/releases/download/v${JADX_VERSION}/jadx-${JADX_VERSION}.zip" \
 && unzip -q /tmp/jadx.zip -d /opt/jadx \
 && rm /tmp/jadx.zip \
 && ln -s /opt/jadx/bin/jadx /usr/local/bin/jadx \
 && ln -s /opt/jadx/bin/jadx-gui /usr/local/bin/jadx-gui

# NodeSource Node 22 — Ubuntu 24.04's default nodejs may be too old for Claude Code
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y nodejs \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (top layer — most churn)
RUN npm install -g @anthropic-ai/claude-code

# Custom helper binaries (sal2sigrok, etc.).
COPY docker/bin/ /usr/local/bin/hydra/
RUN ln -s /usr/local/bin/hydra/sal2sigrok /usr/local/bin/sal2sigrok

WORKDIR /workspace
