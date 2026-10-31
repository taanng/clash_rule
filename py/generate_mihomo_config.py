#!/usr/bin/env python3
"""Generate a complete Mihomo configuration from Custom_Clash_custom.ini."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = ROOT / "Custom_Clash_custom.ini"
DEFAULT_SOURCE = ROOT / "provider.local.yaml"
DEFAULT_OUTPUT = ROOT / "yaml" / "mihomo-config.yaml"
BUILTIN_TARGETS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Mihomo YAML using the local rule template."
    )
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provider-name", help="Override the provider name")
    parser.add_argument("--provider-url", help="Override the provider URL")
    parser.add_argument("--provider-interval", type=int, help="Provider refresh seconds")
    return parser.parse_args()


def load_provider_config(args: argparse.Namespace) -> tuple[str, str, int]:
    provider = {}
    if args.source.exists():
        raw = yaml.safe_load(args.source.read_text(encoding="utf-8")) or {}
        provider = raw.get("provider", raw)
        if not isinstance(provider, dict):
            raise ValueError(f"{args.source} must contain a provider mapping")

    name = args.provider_name or provider.get("name") or "nodes"
    url = args.provider_url or provider.get("url")
    interval = (
        args.provider_interval
        or provider.get("interval")
        or 3600
    )

    if not isinstance(name, str) or not name.strip():
        raise ValueError("provider name is required")
    if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("provider URL must be an absolute HTTP(S) URL")
    if not isinstance(interval, int) or interval < 60:
        raise ValueError("provider interval must be an integer of at least 60 seconds")
    return name.strip(), url.strip(), interval


def read_template(path: Path) -> tuple[list[str], list[str]]:
    rulesets: list[str] = []
    groups: list[str] = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if line.startswith("ruleset="):
            rulesets.append(line.removeprefix("ruleset="))
        elif line.startswith("custom_proxy_group="):
            groups.append(line.removeprefix("custom_proxy_group="))
    if not rulesets or not groups:
        raise ValueError(f"{path} does not contain rulesets and proxy groups")
    return rulesets, groups


def provider_id_for_url(url: str, used: set[str]) -> str:
    filename = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    stem = re.sub(r"\.(?:ya?ml|mrs|list|txt)$", "", filename, flags=re.I)
    base = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "rules"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def provider_options(url: str, source: str, interval: str) -> tuple[str, str]:
    if source == "domain":
        behavior = "domain"
        rule_format = "mrs" if urlsplit(url).path.lower().endswith(".mrs") else "yaml"
    elif source == "classic":
        behavior = "classical"
        rule_format = "text" if urlsplit(url).path.lower().endswith(".list") else "yaml"
    else:
        behavior = "classical"
        rule_format = "text" if urlsplit(url).path.lower().endswith(".list") else "yaml"
    return behavior, rule_format


def parse_rulesets(
    rulesets: list[str],
) -> tuple[dict[str, dict[str, object]], list[str]]:
    providers: dict[str, dict[str, object]] = {}
    rules: list[str] = []
    used_provider_ids: set[str] = set()

    for entry in rulesets:
        group, separator, rest = entry.partition(",")
        if not separator or not group or not rest:
            raise ValueError(f"invalid ruleset: {entry}")

        if rest.startswith("[]"):
            inline = rest[2:].split(",")
            rule_type = inline[0].upper()
            if rule_type == "FINAL":
                rules.append(f"MATCH,{group}")
            elif rule_type in {"GEOSITE", "GEOIP"} and len(inline) >= 2:
                rule = f"{rule_type},{inline[1]},{group}"
                if len(inline) >= 3 and inline[2] == "no-resolve":
                    rule += ",no-resolve"
                rules.append(rule)
            else:
                raise ValueError(f"unsupported inline ruleset: {entry}")
            continue

        source = ""
        if rest.startswith("clash-domain:"):
            source = "domain"
            rest = rest.removeprefix("clash-domain:")
        elif rest.startswith("clash-classic:"):
            source = "classic"
            rest = rest.removeprefix("clash-classic:")

        url, separator, interval_text = rest.partition(",")
        interval = interval_text if separator and interval_text.isdigit() else "86400"
        behavior, rule_format = provider_options(url, source, interval)
        provider_id = provider_id_for_url(url, used_provider_ids)
        providers[provider_id] = {
            "type": "http",
            "behavior": behavior,
            "format": rule_format,
            "interval": int(interval),
            "url": url,
        }
        rules.append(f"RULE-SET,{provider_id},{group}")

    return providers, rules


def parse_proxy_groups(
    entries: list[str], provider_name: str
) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []

    for entry in entries:
        fields = entry.split("`")
        if len(fields) < 2:
            raise ValueError(f"invalid proxy group: {entry}")

        name = fields[0].strip()
        group_type = fields[1].strip().split(",", 1)[0]
        tokens = [field.strip() for field in fields[2:]]

        if group_type == "fallback":
            url_index = next(
                (i for i, token in enumerate(tokens) if token.startswith(("http://", "https://"))),
                None,
            )
            if url_index is None:
                raise ValueError(f"fallback group has no health-check URL: {entry}")
            patterns = [token for token in tokens[:url_index] if token]
            health_url = tokens[url_index]
            interval = 300
            if url_index + 1 < len(tokens):
                interval_text = tokens[url_index + 1].split(",", 1)[0]
                if interval_text.isdigit():
                    interval = int(interval_text)
            group: dict[str, object] = {
                "name": name,
                "type": "fallback",
                "use": [provider_name],
                "url": health_url,
                "interval": interval,
            }
            if patterns:
                group["filter"] = "|".join(f"(?:{pattern})" for pattern in patterns)
            groups.append(group)
            continue

        if group_type != "select":
            raise ValueError(f"unsupported proxy group type {group_type!r}: {entry}")

        proxies: list[str] = []
        use_provider = False
        filters: list[str] = []
        for token in tokens:
            if not token:
                continue
            if token == ".*":
                use_provider = True
            elif token.startswith("[]"):
                target = token[2:].strip()
                if target and target not in proxies:
                    proxies.append(target)
            elif token in BUILTIN_TARGETS:
                if token not in proxies:
                    proxies.append(token)
            elif token.startswith(("http://", "https://")):
                continue
            else:
                filters.append(token)

        group = {"name": name, "type": "select"}
        if proxies:
            group["proxies"] = proxies
        if use_provider:
            group["use"] = [provider_name]
        if filters:
            group["filter"] = "|".join(f"(?:{pattern})" for pattern in filters)
        if len(group) == 2:
            raise ValueError(f"select group has no targets: {entry}")
        groups.append(group)

    return groups


def build_config(
    provider_name: str, provider_url: str, provider_interval: int, template: Path
) -> tuple[dict[str, object], dict[str, int]]:
    ruleset_entries, group_entries = read_template(template)
    rule_providers, rules = parse_rulesets(ruleset_entries)
    proxy_groups = parse_proxy_groups(group_entries, provider_name)

    config: dict[str, object] = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": True,
        "unified-delay": True,
        "tcp-concurrent": True,
        "find-process-mode": "off",
        "geox-url": {
            "geoip": "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.dat",
            "geosite": "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geosite.dat",
            "mmdb": "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb",
        },
        "geo-auto-update": True,
        "geo-update-interval": 24,
        "dns": {
            "enable": True,
            "ipv6": True,
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "fake-ip-filter": [
                "*.lan",
                "*.local",
                "+.msftconnecttest.com",
                "+.msftncsi.com",
            ],
            "default-nameserver": ["223.5.5.5", "119.29.29.29"],
            "nameserver": [
                "https://dns.alidns.com/dns-query",
                "https://doh.pub/dns-query",
            ],
            "proxy-server-nameserver": [
                "https://dns.alidns.com/dns-query",
                "https://doh.pub/dns-query",
            ],
            "nameserver-policy": {
                "geosite:cn,private": [
                    "https://dns.alidns.com/dns-query",
                    "https://doh.pub/dns-query",
                ],
                "geosite:geolocation-!cn": [
                    "https://dns.google/dns-query#🚀 手动选择",
                    "https://cloudflare-dns.com/dns-query#🚀 手动选择",
                ],
            },
        },
        "proxy-providers": {
            provider_name: {
                "type": "http",
                "url": provider_url,
                "path": f"./providers/{provider_name}.yaml",
                "interval": provider_interval,
                "health-check": {
                    "enable": True,
                    "url": "https://www.gstatic.com/generate_204",
                    "interval": 300,
                },
            }
        },
        "proxy-groups": proxy_groups,
        "rule-providers": rule_providers,
        "rules": rules,
    }
    validate_config(config, provider_name)
    stats = {
        "groups": len(proxy_groups),
        "rule_providers": len(rule_providers),
        "rules": len(rules),
    }
    return config, stats


def validate_config(config: dict[str, object], provider_name: str) -> None:
    groups = config["proxy-groups"]
    providers = config["proxy-providers"]
    rules = config["rules"]
    rule_providers = config["rule-providers"]
    if not isinstance(groups, list) or not isinstance(rules, list):
        raise ValueError("proxy-groups and rules must be lists")
    if not isinstance(providers, dict) or provider_name not in providers:
        raise ValueError("the node provider is missing")
    if not isinstance(rule_providers, dict):
        raise ValueError("rule-providers must be a mapping")

    group_names = {group["name"] for group in groups if isinstance(group, dict)}
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("invalid proxy group")
        for target in group.get("proxies", []):
            if target not in group_names and target not in BUILTIN_TARGETS:
                raise ValueError(f"group {group['name']!r} references missing {target!r}")
        for target in group.get("use", []):
            if target not in providers:
                raise ValueError(f"group {group['name']!r} uses missing provider {target!r}")

    for rule in rules:
        if rule.startswith("MATCH,"):
            target = rule.split(",", 1)[1]
        elif rule.startswith("RULE-SET,"):
            parts = rule.split(",")
            if len(parts) < 3:
                raise ValueError(f"invalid rule: {rule}")
            if parts[1] not in rule_providers:
                raise ValueError(f"rule references missing provider: {rule}")
            target = parts[2]
        else:
            parts = rule.split(",")
            if len(parts) < 3:
                raise ValueError(f"invalid rule: {rule}")
            target = parts[2]
        if target not in group_names:
            raise ValueError(f"rule references missing group {target!r}: {rule}")


def main() -> int:
    args = parse_args()
    try:
        provider_name, provider_url, provider_interval = load_provider_config(args)
        config, stats = build_config(
            provider_name, provider_url, provider_interval, args.template
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Generated by generate_mihomo_config.py.\n"
        "# Contains a private provider URL; do not publish this file without protection.\n"
    )
    rendered = yaml.safe_dump(
        config,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=120,
    )
    args.output.write_text(header + rendered, encoding="utf-8")
    args.output.chmod(0o600)
    print(f"wrote {args.output}")
    print(
        "generated: "
        f"{stats['groups']} groups, {stats['rule_providers']} rule providers, "
        f"{stats['rules']} rules"
    )
    parsed_url = urlsplit(provider_url)
    print(f"provider: {provider_name} at {parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
