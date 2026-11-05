# Start from an image that already has PyTorch + DEMUCS installed (~3.5 GB).
# Because those layers already exist on Docker Hub, `docker push` only
# uploads the few small layers we add below.
FROM xserrat/facebook-demucs:latest

RUN pip3 install --no-cache-dir minio redis requests

WORKDIR /srv
COPY worker-server.py /srv/

ENV PYTHONUNBUFFERED=1 \
    WORK_DIR=/tmp/demucs \
    TORCH_HOME=/data/models

# The base image's ENTRYPOINT is a login bash shell (so its Python env is
# activated). Set it explicitly so our CMD is run through that shell.
ENTRYPOINT ["/bin/bash", "--login", "-c"]
CMD ["python3 -u /srv/worker-server.py"]
