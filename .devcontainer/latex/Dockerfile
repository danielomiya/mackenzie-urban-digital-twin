# syntax=docker/dockerfile:1

ARG DEBIAN_RELEASE=trixie

# ---------------------------------------------------------------------------
# Stage 1: TeX Live (scheme-basic + packages from tex-packages.txt)
# ---------------------------------------------------------------------------
FROM debian:${DEBIAN_RELEASE}-slim AS texlive

# Fail the build if the installer download fails mid-pipe
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG TL_MIRROR=https://mirror.ctan.org/systems/texlive/tlnet

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl perl xz-utils \
    && rm -rf /var/lib/apt/lists/*

COPY texlive.profile /tmp/texlive.profile
RUN mkdir /tmp/install-tl \
    && curl -fsSL "${TL_MIRROR}/install-tl-unx.tar.gz" \
    | tar -xz -C /tmp/install-tl --strip-components=1 \
    && sed -i 's/\r$//' /tmp/texlive.profile \
    && perl /tmp/install-tl/install-tl -profile /tmp/texlive.profile -repository "${TL_MIRROR}" \
    && ln -s "/usr/local/texlive/bin/$(uname -m)-linux" /opt/texbin \
    && rm -rf /tmp/install-tl /tmp/texlive.profile
ENV PATH=/opt/texbin:${PATH}

# Separate step: editing tex-packages.txt only re-runs this, not the base install.
COPY tex-packages.txt /tmp/tex-packages.txt
RUN pkgs="$(sed 's/\r$//; s/#.*//' /tmp/tex-packages.txt | xargs)" \
    && tlmgr option repository "${TL_MIRROR}" \
    && if [ -n "${pkgs}" ]; then tlmgr install ${pkgs}; fi \
    # Caches and logs tlmgr does not need (the remote package db is re-fetched on demand)
    && rm -rf /usr/local/texlive/tlpkg/texlive.tlpdb.main.* \
    /usr/local/texlive/tlpkg/backups/* \
    /usr/local/texlive/install-tl.log \
    /usr/local/texlive/texmf-var/web2c/*/*.log

# ---------------------------------------------------------------------------
# Stage 2: the dev container
# ---------------------------------------------------------------------------
FROM debian:${DEBIAN_RELEASE}-slim

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

# perl: latexmk and tlmgr | curl, xz-utils: tlmgr downloads at runtime
# git, less: source control in VS Code | procps: used by the VS Code server
# python3: runs latexminted for minted v3 (Pygments ships bundled with the minted package)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates curl git less perl procps python3 xz-utils libyaml-tiny-perl libfile-homedir-perl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${USER_GID}" "${USERNAME}" \
    && useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home --shell /bin/bash "${USERNAME}" \
    # Target of the extensions volume, pre-created so the dev user owns it
    && mkdir -p "/home/${USERNAME}/.vscode-server/extensions" \
    && chown -R "${USERNAME}:${USERNAME}" "/home/${USERNAME}/.vscode-server"

# Owned by the dev user so `tlmgr install` / `texpkg` work without sudo.
# --chown here (instead of a later chown -R) keeps the tree in a single layer.
COPY --from=texlive --chown=${USERNAME}:${USERNAME} /usr/local/texlive /usr/local/texlive

COPY texpkg /usr/local/bin/texpkg
RUN sed -i 's/\r$//' /usr/local/bin/texpkg \
    && chmod 755 /usr/local/bin/texpkg \
    && ln -s "/usr/local/texlive/bin/$(uname -m)-linux" /opt/texbin \
    # Login shells reset PATH from /etc/profile; this puts TeX Live back
    && echo 'export PATH="/opt/texbin:$PATH"' > /etc/profile.d/texlive.sh

ENV PATH=/opt/texbin:${PATH} \
    LANG=C.UTF-8

USER ${USERNAME}
