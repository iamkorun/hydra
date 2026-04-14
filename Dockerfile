FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

# System layer (rare churn)
COPY docker/apt-packages.txt /tmp/apt-packages.txt
RUN apt-get update \
 && xargs -a /tmp/apt-packages.txt apt-get install -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

# Python CTF stack (rare churn)
COPY docker/requirements-ctf.txt /tmp/requirements-ctf.txt
RUN pip install -r /tmp/requirements-ctf.txt

# Playwright Chromium for JS-heavy web challenges (~300 MB).
# --with-deps pulls apt runtime libs; must run before apt lists are cleaned.
RUN playwright install --with-deps chromium

# Web tooling
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ffuf gobuster sqlmap nikto wfuzz \
 && rm -rf /var/lib/apt/lists/*

# Reverse tooling
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    radare2 ltrace strace upx-ucl \
 && rm -rf /var/lib/apt/lists/*

# Crypto CLI (pari-gp factoring, command-line number theory).
# Note: `sagemath` was removed from Ubuntu starting with noble (24.04).
# For Sage-only attacks (Coppersmith, LLL), use fpylll/flatter from pip (below)
# or fall back to sympy + RsaCtfTool. If a chal truly needs sage, a specialist
# can `apt install conda && conda install -c conda-forge sage` ad-hoc in work/.
RUN apt-get update \
 && apt-get install -y --no-install-recommends pari-gp \
 && rm -rf /var/lib/apt/lists/*

# Forensics (zsteg is a Ruby gem — installed below, not here).
# sleuthkit: fls, icat, mmls (disk-image forensics).
# binaryen: wasm-decompile for WASM reverse-engineering chals.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    binwalk foremost steghide tshark exiftool sleuthkit binaryen \
 && rm -rf /var/lib/apt/lists/*

# External git-installed tools
RUN git clone --depth 1 https://github.com/RsaCtfTool/RsaCtfTool /opt/RsaCtfTool \
 && pip install -r /opt/RsaCtfTool/requirements.txt \
 && ln -s /opt/RsaCtfTool/RsaCtfTool.py /usr/local/bin/RsaCtfTool
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
 && rm /tmp/ghidra.zip \
 && ln -s "/opt/ghidra_${GHIDRA_VERSION}_PUBLIC/support/analyzeHeadless" /usr/local/bin/analyzeHeadless

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

WORKDIR /workspace
