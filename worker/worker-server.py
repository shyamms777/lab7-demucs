#!/usr/bin/env python3
"""
Waveform-separation worker for MSaaS.

Loop forever:
  1. BLPOP a job ticket from Redis list "toWorker"   (blocks until work exists)
  2. Download  queue/<hash>.mp3            from RustFS (S3) to local disk
  3. Run DEMUCS as a subprocess            (slow: ~3-4x song length, lots of RAM)
  4. Upload    output/<hash>-<part>.mp3    for part in bass/drums/vocals/other
  5. Delete the input, fire the optional webhook callback

Because the worker *pulls* work, you scale throughput by simply running more
worker pods -- no code change, no load balancer.
"""
import glob
import json
import os
import platform
import shutil
import subprocess
import sys
import time

import redis
import requests
from minio import Minio   # generic S3 client; talks to RustFS

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
S3_HOST = os.getenv("S3_HOST", "localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "rustfs-lab-user")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "replace-this-demo-secret")
DEMUCS_MODEL = os.getenv("DEMUCS_MODEL", "")   # "" = demucs default model
WORK_DIR = os.getenv("WORK_DIR", "/tmp/demucs")

QUEUE_KEY = "toWorker"
PROCESSING_KEY = "processing"   # jobs currently being worked on
FAILED_KEY = "failed"           # jobs that raised an error
LOG_KEY = "logging"
QUEUE_BUCKET = "queue"
OUTPUT_BUCKET = "output"
TRACKS = ("bass", "drums", "vocals", "other")

redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=0)
s3_client = Minio(S3_HOST, access_key=S3_ACCESS_KEY,
                     secret_key=S3_SECRET_KEY, secure=False)

INFO_KEY = f"{platform.node()}.worker.info"
DEBUG_KEY = f"{platform.node()}.worker.debug"


def _log(level, key, message):
    print(f"{level}: {message}", file=sys.stdout, flush=True)
    try:
        redis_client.lpush(LOG_KEY, f"{key}:{message}")
    except redis.RedisError:
        pass


def log_info(message):
    _log("INFO", INFO_KEY, message)


def log_debug(message):
    _log("DEBUG", DEBUG_KEY, message)


def run_demucs(input_path, output_dir, model=None):
    """Run DEMUCS in a child process; return {part: path_to_mp3}."""
    cmd = [sys.executable, "-m", "demucs.separate", "--mp3", "--out", output_dir]
    model = model or DEMUCS_MODEL
    if model:
        cmd += ["-n", model]
    cmd.append(input_path)
    log_debug(f"running: {' '.join(cmd)}")
    started = time.time()
    # subprocess.run (unlike os.system) gives us the exit code AND the output
    # without going through a shell -- no quoting bugs, no shell injection.
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Exit code -9 / 137 almost always means "killed: out of memory".
        raise RuntimeError(f"demucs exited {result.returncode}: "
                           f"{result.stderr[-2000:]}")
    log_info(f"demucs finished in {time.time() - started:.1f}s")

    # Output lands in <output_dir>/<model_name>/<songhash>/<part>.mp3.
    # The model directory name changes between demucs versions
    # (mdx_extra_q, htdemucs, ...) so search instead of hard-coding it.
    stem = os.path.splitext(os.path.basename(input_path))[0]
    parts = {}
    for part in TRACKS:
        matches = glob.glob(os.path.join(output_dir, "*", stem, f"{part}.mp3"))
        if not matches:
            raise RuntimeError(f"demucs produced no {part}.mp3 in {output_dir}")
        parts[part] = matches[0]
    return parts


def fire_callback(callback, songhash):
    """POST the caller-supplied payload. Failure is allowed (per README)."""
    if not callback or "url" not in callback:
        return
    try:
        requests.post(callback["url"],
                      json={"hash": songhash, "data": callback.get("data")},
                      timeout=5)
        log_debug(f"callback to {callback['url']} sent")
    except requests.RequestException as err:
        log_debug(f"callback to {callback['url']} failed: {err}")


def process(job):
    songhash = job["hash"]
    job_dir = os.path.join(WORK_DIR, songhash)
    in_path = os.path.join(job_dir, f"{songhash}.mp3")
    out_dir = os.path.join(job_dir, "output")
    os.makedirs(out_dir, exist_ok=True)
    try:
        log_info(f"starting {songhash}")
        s3_client.fget_object(QUEUE_BUCKET, f"{songhash}.mp3", in_path)

        parts = run_demucs(in_path, out_dir, job.get("model"))

        if not s3_client.bucket_exists(OUTPUT_BUCKET):
            s3_client.make_bucket(OUTPUT_BUCKET)
        for part, path in parts.items():
            s3_client.fput_object(OUTPUT_BUCKET, f"{songhash}-{part}.mp3",
                                     path, content_type="audio/mpeg")
        s3_client.remove_object(QUEUE_BUCKET, f"{songhash}.mp3")
        log_info(f"finished {songhash}: uploaded {', '.join(parts)}")
        fire_callback(job.get("callback"), songhash)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)   # don't fill the disk


def main():
    log_info(f"worker up; redis={REDIS_HOST}:{REDIS_PORT} s3={S3_HOST}")
    while True:
        try:
            # BLMOVE atomically pops from toWorker and pushes onto
            # "processing". If this pod crashes mid-song (e.g. OOM-killed),
            # the ticket is still in "processing" instead of being lost.
            # timeout=0 => block forever; costs no CPU while idle.
            raw = redis_client.blmove(QUEUE_KEY, PROCESSING_KEY, 0,
                                      "RIGHT", "LEFT")
        except redis.ConnectionError as err:
            print(f"redis connection error: {err}; retrying in 5s", flush=True)
            time.sleep(5)
            continue
        try:
            process(json.loads(raw))
        except Exception as err:   # keep the worker alive on a bad job
            log_info(f"job failed: {err}")
            redis_client.lpush(FAILED_KEY, raw)   # park it for inspection
        # Not in a `finally:` on purpose: if the worker is stopped mid-job
        # (Ctrl+C, SIGKILL, OOM), the ticket must STAY in "processing".
        redis_client.lrem(PROCESSING_KEY, 1, raw)


if __name__ == "__main__":
    main()
