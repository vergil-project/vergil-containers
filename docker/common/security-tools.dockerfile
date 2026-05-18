# --- Security tools -----------------------------------------------------------
ARG TARGETARCH
ARG SCORECARD_VERSION=5.5.0

RUN curl -fsSL "https://github.com/ossf/scorecard/releases/download/v${SCORECARD_VERSION}/scorecard_${SCORECARD_VERSION}_linux_${TARGETARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin/ scorecard
