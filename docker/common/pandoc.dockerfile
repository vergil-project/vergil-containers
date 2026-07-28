# --- pandoc ------------------------------------------------------------------
# Universal document converter, installed from the base distro's apt repo.
# Driver: markdown -> .docx for publishing research reports (a .docx imports as
# a native Google Doc). pandoc's docx writer is native and needs NO LaTeX, so
# --no-install-recommends keeps texlive (only required for PDF output) out of
# the image. PDF output, if wanted later, is a separate opt-in decision.
#
# Unpinned by design: apt pandoc floats cleanly by dropping the version, so it
# stays out of the docker/pins/ mechanism-pin set (which exists only for tools
# whose download URL requires an explicit version). See docker/pins/pins.yml.
RUN apt-get update && \
    apt-get install -y --no-install-recommends pandoc && \
    rm -rf /var/lib/apt/lists/*
