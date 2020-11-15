import json
import logging
import os
import subprocess
import typing
from collections import defaultdict
from time import time as current_time

TARGET_CAHCE_FILEPATH = "/tmp/icmp_nodes.json"

tracepath_cmd = ["/usr/bin/traceroute", "-I", "-n", "-q", "1", ""]

TARGETS = [
    # public-dns.info
    "88.208.245.221",
    "198.199.103.49",
    "8.8.8.8",
    "8.8.4.4",
    "194.55.30.46",
    "87.250.250.242",
    "195.19.220.16",
]


def get_nodes_list() -> typing.List[str]:
    """Search common nodes by tracepath.
    """
    with_nodes = defaultdict(int)
    for addr in TARGETS:
        nodes = set()
        tracepath_cmd[-1] = addr
        result = subprocess.run(tracepath_cmd, capture_output=True, text=True)
        lines = result.stdout.split("\n")
        for line in lines:
            if addr in line:
                continue
            if "ms" in line:
                try:
                    index, node, *_ = line.split()
                    index = int(index.strip())
                    node = node.strip()
                except Exception:
                    continue
                else:
                    if index > 2:
                        for delta in range(5):
                            nodes.add((index - delta, node))
                            nodes.add((index + delta, node))

        for node in nodes:
            with_nodes[node] += 1

    return list(
        set(addr for (_, addr), top in with_nodes.items() if top >= 2)
    )


def get_targets(
    logger: logging.Logger,
    cache_timeout: int = 12 * 3600
) -> typing.List[str]:
    """ICMP targets.
    """
    exists = []
    update = True
    now = current_time()
    try:
        with open(TARGET_CAHCE_FILEPATH) as cache:
            data = json.loads(cache.read())

        if data:
            update = now - data["timestamp"] > cache_timeout
            exists.extend(data["targets"])
    except Exception:
        pass

    if update or not exists:
        exists.extend(get_nodes_list())
        if update and exists:
            try:
                with open(TARGET_CAHCE_FILEPATH, "w") as cache:
                    cache.write(
                        json.dumps({
                            "timestamp": now,
                            "targets": exists
                        })
                    )
            except Exception as err:
                logger.error(f"Cahce {TARGET_CAHCE_FILEPATH} error:", err)

    return exists


def ping(targets: list) -> float:
    """The ping time to first available address.
    """
    result = 0
    for target in targets:
        ping_result = subprocess.run(
            ["ping", "-c1", "-w2", target],
            capture_output=True,
            text=True
        )
        lines = ping_result.stdout.split("\n")
        for line in lines:
            if "time=" in line:
                *_, in_ms = line.split("=")
                if " " in in_ms:
                    in_ms, *_ = in_ms.split()
                    result = float(in_ms)

            if result > 0:
                break

    return result


def check(logger: logging.Logger) -> bool:
    """Check internet access.
    """
    ping_time = 0
    prog, *_ = tracepath_cmd
    if os.path.exists(prog):
        targets = get_targets(logger)
        if not targets:
            msg = "Network checking: skip checking (no target)"
            logger.warning(msg)

        try:
            ping_time = ping(targets)
        except Exception as err:
            logger.error(f"Ping error: {err}")

        if ping_time:
            logger.info(f"ping time: {ping_time}")
        else:
            logger.warning(f"Not access to target: {targets}")
    else:
        logger.error(f"No soft: {prog}")

    return ping_time > 0
