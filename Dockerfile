# Base image
FROM ubuntu:22.04

# Working directory, Streamlit does not work at root
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt /app/

# Install Python and necessary system packages
RUN apt-get update && \
	apt-get install -y --no-install-recommends \
		python3-pip \
		python-dev-is-python3 \
		build-essential \
		vim \
		clamav \
		clamav-daemon \
		ca-certificates \
		curl && \
	rm -rf /var/lib/apt/lists/*

# Ensure virus definitions exist (best effort) and provide a wrapper for runtime scans
RUN freshclam || true

RUN mkdir -p /var/log/clamav /var/run/clamav && \
	chown -R clamav:clamav /var/log/clamav /var/run/clamav

RUN cat <<'EOF' >/usr/local/bin/clamdscan-wrapper && \
	chmod +x /usr/local/bin/clamdscan-wrapper
#!/bin/bash
set -euo pipefail

TARGET="$1"

# Start clamd if it is not already running
if ! pgrep -x clamd >/dev/null 2>&1; then
	freshclam --quiet || true
	clamd --foreground --config-file=/etc/clamav/clamd.conf &
	CLAMD_PID=$!
	for _ in $(seq 1 15); do
		if [ -S /var/run/clamav/clamd.ctl ]; then
			break
		fi
		sleep 1
	done
fi

if clamdscan --config-file=/etc/clamav/clamd.conf --no-summary "$TARGET"; then
	exit 0
fi

clamscan --no-summary "$TARGET"
EOF

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Clear pip cache
RUN rm -rf /root/.cache/pip

# Copy the current code to the image
COPY . .

EXPOSE 80

# Set environment variables to retrieve the build time as an environment variable
# docker build --build-arg BUILD_TIME="$(date '+%d/%m/%Y %Hh%M')" -t plidockerregistry.azurecr.io/rai .
ARG BUILD_TIME
ARG STATIC_ASSET_VERSION
ENV BUILD_TIME=${BUILD_TIME}
ENV STATIC_ASSET_VERSION=${STATIC_ASSET_VERSION}

# Run with Streamlit
# CMD [ "streamlit", "run", "streamlit_ui_main.py", "--server.port=80", "--server.address=0.0.0.0", "--server.enableWebsocketCompression=false" ]

# Run with htmx
CMD ["uvicorn", "htmx_ui_main:app", "--host", "0.0.0.0", "--port", "80"]