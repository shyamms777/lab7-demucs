#!/usr/bin/env python3
"""
REST front-end for Music-Separation-as-a-Service (MSaaS).

Responsibilities (and NOTHING else -- the slow work happens in the worker):
  1. Accept a base64-encoded MP3 over HTTP.
  2. Store the raw MP3 in object storage (RustFS bucket "queue").
  3. Push a small JSON "job ticket" onto a Redis list ("toWorker").
  4. Serve the separated tracks back out of RustFS bucket "output".

Configuration comes from environment variables so the SAME code runs on your
laptop (talking to port-forwarded services on localhost) and inside Kubernetes
(talking to the `redis` and `rustfs` Services by DNS name).
"""
import base64
import binascii
import hashlib
import io
import json
import os
import platform
import sys

import redis
from flask import Flask, Response, jsonify, request, send_file
from minio import Minio   # generic S3 client; talks to RustFS
from minio.error import S3Error

# --------------------------------------------------------------------------
# Configuration (12-factor style: config lives in the environment)
# --------------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
S3_HOST = os.getenv("S3_HOST", "localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "rustfs-lab-user")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "replace-this-demo-secret")

QUEUE_KEY = "toWorker"        # Redis list the worker BLPOPs from
LOG_KEY = "logging"           # Redis list the logs pod BLPOPs from
QUEUE_BUCKET = "queue"        # RustFS bucket: songs waiting to be separated
OUTPUT_BUCKET = "output"      # RustFS bucket: <songhash>-<track>.mp3 results
TRACKS = ("bass", "drums", "vocals", "other")

# --------------------------------------------------------------------------
# Clients. Created once at import time and reused (connection pooling).
# Tests replace these module globals with fakes.
# --------------------------------------------------------------------------
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=0)
s3_client = Minio(S3_HOST, access_key=S3_ACCESS_KEY,
                     secret_key=S3_SECRET_KEY, secure=False)

app = Flask(__name__)
# Songs arrive base64-encoded (~33% bigger than the MP3). Allow up to 64 MB.
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

# --------------------------------------------------------------------------
# Logging helpers -- see logs/README.md. Messages go to stdout (so
# `kubectl logs` sees them) AND to the Redis "logging" list (so the logs pod
# shows a single merged stream from every rest + worker pod).
# --------------------------------------------------------------------------
INFO_KEY = f"{platform.node()}.rest.info"
DEBUG_KEY = f"{platform.node()}.rest.debug"


def _log(level, key, message):
    print(f"{level}: {message}", file=sys.stdout, flush=True)
    try:
        redis_client.lpush(LOG_KEY, f"{key}:{message}")
    except redis.RedisError:
        pass  # never let logging take the server down


def log_info(message):
    _log("INFO", INFO_KEY, message)


def log_debug(message):
    _log("DEBUG", DEBUG_KEY, message)


def ensure_bucket(name):
    if not s3_client.bucket_exists(name):
        s3_client.make_bucket(name)


def normalize_track(track):
    """Accept 'vocals' or 'vocals.mp3' (and the README's 'base' typo)."""
    name = track[:-4] if track.endswith(".mp3") else track
    return "bass" if name == "base" else name


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def hello():
    # Health check endpoint -- the GKE load balancer requires a 200 on "/".
    return "<h1>Music Separation Server</h1><p>Use a valid endpoint</p>"


@app.route("/apiv1/separate", methods=["POST"])
def separate():
    body = request.get_json(force=True, silent=True)
    if not body or "mp3" not in body:
        return jsonify({"error": "JSON body with base64 field 'mp3' required"}), 400

    try:
        mp3_bytes = base64.b64decode(body["mp3"], validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"error": "'mp3' is not valid base64"}), 400

    # Content-addressed ID: the same song always gets the same hash, so a
    # duplicate upload is naturally idempotent.
    songhash = hashlib.sha224(mp3_bytes).hexdigest()

    ensure_bucket(QUEUE_BUCKET)
    s3_client.put_object(QUEUE_BUCKET, f"{songhash}.mp3",
                            io.BytesIO(mp3_bytes), length=len(mp3_bytes),
                            content_type="audio/mpeg")

    # The job ticket is tiny -- the big MP3 lives in RustFS, not in Redis.
    job = {
        "hash": songhash,
        "model": body.get("model"),
        "callback": body.get("callback"),
    }
    redis_client.lpush(QUEUE_KEY, json.dumps(job))
    log_info(f"queued {songhash} ({len(mp3_bytes)} bytes)")

    return jsonify({"hash": songhash, "reason": "Song enqueued for separation"})


@app.route("/apiv1/queue", methods=["GET"])
@app.route("/apiv1/queue/", methods=["GET"])
def queue():
    raw = redis_client.lrange(QUEUE_KEY, 0, -1)
    hashes = []
    for item in raw:
        try:
            hashes.append(json.loads(item)["hash"])
        except (ValueError, KeyError, TypeError):
            hashes.append(item.decode("utf-8", "replace"))
    return jsonify({"queue": hashes})


@app.route("/apiv1/track/<songhash>/<track>", methods=["GET"])
def track(songhash, track):
    name = normalize_track(track)
    if name not in TRACKS:
        return jsonify({"error": f"track must be one of {TRACKS}"}), 400
    obj_name = f"{songhash}-{name}.mp3"
    try:
        obj = s3_client.get_object(OUTPUT_BUCKET, obj_name)
        data = obj.read()
        obj.close()
        obj.release_conn()
    except S3Error as err:
        if err.code in ("NoSuchKey", "NoSuchBucket"):
            return jsonify({"error": f"{obj_name} not found (still processing?)"}), 404
        raise
    log_debug(f"served {obj_name}")
    return send_file(io.BytesIO(data), mimetype="audio/mpeg",
                     as_attachment=True, download_name=f"{name}.mp3")


@app.route("/apiv1/remove/<songhash>/<track>", methods=["GET", "DELETE"])
def remove(songhash, track):
    name = normalize_track(track)
    if name not in TRACKS:
        return jsonify({"error": f"track must be one of {TRACKS}"}), 400
    obj_name = f"{songhash}-{name}.mp3"
    try:
        s3_client.remove_object(OUTPUT_BUCKET, obj_name)
    except S3Error as err:
        if err.code != "NoSuchBucket":
            raise
    log_info(f"removed {obj_name}")
    return jsonify({"hash": songhash, "track": name, "reason": "Track removed"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    log_info(f"REST server starting on port {port}")
    # 0.0.0.0 = listen on every interface. Inside a container, 127.0.0.1
    # would only be reachable from inside that same container!
    app.run(host="0.0.0.0", port=port)
