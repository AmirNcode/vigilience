# Vigilience PIN gate. Standard library only; no packages installed.
FROM python:3.13.9-alpine3.22
COPY pin_gate.py /app/pin_gate.py
USER 65534:65534
ENTRYPOINT ["python3", "-u", "/app/pin_gate.py"]
