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

# Crypto (sagemath is heavy — ~2 GB)
RUN apt-get update \
 && apt-get install -y --no-install-recommends sagemath \
 && rm -rf /var/lib/apt/lists/*

# Forensics
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    binwalk foremost steghide tshark exiftool zsteg \
 && rm -rf /var/lib/apt/lists/*

# External git-installed tools
RUN git clone --depth 1 https://github.com/RsaCtfTool/RsaCtfTool /opt/RsaCtfTool \
 && pip install -r /opt/RsaCtfTool/requirements.txt \
 && ln -s /opt/RsaCtfTool/RsaCtfTool.py /usr/local/bin/RsaCtfTool
RUN gem install one_gadget

# NodeSource Node 22 — Ubuntu 24.04's default nodejs may be too old for Claude Code
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y nodejs \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (top layer — most churn)
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace
