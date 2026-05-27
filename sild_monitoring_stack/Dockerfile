FROM python:3.11-slim

LABEL org.opencontainers.image.title="SILD Filter Sidecar"
LABEL org.opencontainers.image.licenses="AGPL-3.0-only OR LicenseRef-ISCaD-Commercial"
LABEL org.opencontainers.image.source="https://codeberg.org/iscad/cairn"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sild_detector.py .
COPY sild_mllp_filter.py .
COPY sild_mllp_target.py .
COPY sild_mllp_sender.py .
COPY sild_fhir_filter.py .
COPY sild_fhir_target.py .
COPY sild_fhir_sender.py .
COPY load_generator.py .
COPY samples/ ./samples/
COPY samples_fhir/ ./samples_fhir/

# Default command is overridden per service in docker-compose
CMD ["python", "-u", "sild_mllp_filter.py"]
