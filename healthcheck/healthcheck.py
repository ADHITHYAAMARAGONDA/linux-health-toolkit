#!/usr/bin/env python3
'''Linux health check: disk, memory, load, systemd. Alerts to Discord.'''
import argparse
import json
import logging
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import requests

log = logging.getLogger('healthcheck')


@dataclass(frozen=True)
class Finding:
    key: str
    message: str


@dataclass(frozen=True)
class Config:
    webhook_url: str
    disk_pct: float
    mem_pct: float
    load_per_cpu: float
    cooldown_s: int
    state_file: Path
    watch_services: tuple

    @classmethod
    def from_env(cls):
        services = os.getenv('WATCH_SERVICES', '')
        return cls(
            webhook_url=os.getenv('DISCORD_WEBHOOK_URL', ''),
            disk_pct=float(os.getenv('DISK_THRESHOLD_PCT', '80')),
            mem_pct=float(os.getenv('MEM_THRESHOLD_PCT', '85')),
            load_per_cpu=float(os.getenv('LOAD_PER_CPU_THRESHOLD', '1.5')),
            cooldown_s=int(os.getenv('ALERT_COOLDOWN_SECONDS', '3600')),
            state_file=Path(os.getenv('STATE_FILE', '/var/tmp/healthcheck_state.json')),
            watch_services=tuple(s.strip() for s in services.split(',') if s.strip()),
        )


def check_disk(cfg):
    findings = []
    for part in psutil.disk_partitions(all=False):
        if part.fstype in ('squashfs', 'iso9660'):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        if usage.percent >= cfg.disk_pct:
            findings.append(Finding(
                f'disk:{part.mountpoint}',
                f'Disk {part.mountpoint} is {usage.percent:.0f}% full (limit {cfg.disk_pct:.0f}%)'))
    return findings


def check_memory(cfg):
    pct = psutil.virtual_memory().percent
    if pct >= cfg.mem_pct:
        return [Finding('memory', f'Memory usage is {pct:.0f}% (limit {cfg.mem_pct:.0f}%)')]
    return []


def check_load(cfg):
    per_cpu = os.getloadavg()[1] / (os.cpu_count() or 1)  # 5-minute average
    if per_cpu >= cfg.load_per_cpu:
        return [Finding('load', f'5-min load is {per_cpu:.2f} per CPU (limit {cfg.load_per_cpu})')]
    return []


def _systemctl(*args):
    return subprocess.run(['systemctl', *args], capture_output=True, text=True, timeout=15)


def check_failed_units(cfg):
    try:
        out = _systemctl('--failed', '--no-legend', '--plain').stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.warning('systemctl unavailable; skipping unit checks')
        return []
    units = [line.split()[0] for line in out.splitlines() if line.strip()]
    return [Finding(f'unit:{u}', f'systemd unit {u} has failed') for u in units]


def check_watched_services(cfg):
    findings = []
    for svc in cfg.watch_services:
        try:
            state = _systemctl('is-active', svc).stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if state != 'active':
            label = state or 'unknown'
            findings.append(Finding(f'service:{svc}', f'Service {svc} is {label}'))
    return findings


def load_state(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path, state):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


def reconcile(findings, state, cooldown_s, now):
    '''Decide what to alert on. Mutates state. Returns (alerts, resolved_keys).'''
    current = {f.key: f for f in findings}
    alerts, resolved = [], []
    for key, finding in current.items():
        prev = state.get(key)
        if prev is None or now - prev['last_alert'] >= cooldown_s:
            alerts.append(finding)
            state[key] = {'first_seen': prev['first_seen'] if prev else now, 'last_alert': now}
    for key in list(state):
        if key not in current:
            resolved.append(key)
            del state[key]
    return alerts, resolved


def build_message(host, alerts, resolved):
    lines = []
    if alerts:
        lines.append(f':red_circle: **ALERT on {host}**')
        lines += [f'- {f.message}' for f in alerts]
    if resolved:
        lines.append(f':green_circle: **RECOVERED on {host}**: ' + ', '.join(resolved))
    return '\n'.join(lines)


def send_discord(url, text):
    resp = requests.post(url, json={'content': text}, timeout=10)
    resp.raise_for_status()


CHECKS = (check_disk, check_memory, check_load, check_failed_units, check_watched_services)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='print only; do not send or save state')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    cfg = Config.from_env()

    findings = [f for check in CHECKS for f in check(cfg)]
    state = load_state(cfg.state_file)
    alerts, resolved = reconcile(findings, state, cfg.cooldown_s, time.time())
    if not alerts and not resolved:
        log.info('OK: %d active issue(s), nothing new to report', len(findings))
        return 0

    message = build_message(socket.gethostname(), alerts, resolved)
    if args.dry_run:
        print(message)
        return 0
    if not cfg.webhook_url:
        log.error('DISCORD_WEBHOOK_URL is not set')
        return 2
    try:
        send_discord(cfg.webhook_url, message)
    except requests.RequestException as exc:
        log.error('Discord send failed: %s', exc)
        return 1
    save_state(cfg.state_file, state)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
