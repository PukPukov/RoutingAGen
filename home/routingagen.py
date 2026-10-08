"""Render RoutingA text; only data substitutions are interpreted by Jinja."""

import json
import logging
import time
from pathlib import Path

import dns.exception
import dns.rdata
import dns.rdataclass
import dns.rdatatype
import requests
import yaml
from atomicwrites import atomic_write
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from more_itertools import flatten

LOG = logging.getLogger(__name__)
DATA_ERRORS = (ValueError, TypeError, KeyError, dns.exception.DNSException)


def string_dict(values):
    values = dict.fromkeys(values)
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"Ожидалась строка, получен {type(value).__name__}: {value!r}")
    return values


def exclude(excluded, values):
    excluded = dict.keys(excluded)
    return {value: None for value in dict.keys(values) if value not in excluded}


def finalize(value):
    return ", ".join(dict.keys(value))


def write_text(path, text):
    with atomic_write(path, overwrite=True, encoding="utf-8") as stream:
        stream.write(text)


class Sources:
    def __init__(self, config, session):
        self.session = session
        self.ttl = config["cache"]["ttl_seconds"]
        self.cache_file = Path(config["cache"]["file"])
        self.doh_url = config["dns"]["doh_url"]
        try:
            self.cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if not isinstance(self.cache, dict):
                raise ValueError("корень кеша должен быть объектом")
        except (OSError, ValueError) as exc:
            self.cache = {}
            if self.cache_file.exists():
                LOG.warning("Не удалось прочитать кеш %s: %s", self.cache_file, exc)

    def fetch(self, url, parse):
        """One HTTP/cache path for sources and DNS; parse before saving raw JSON."""
        cached = self.cache.get(url)
        if cached is not None:
            try:
                timestamp = cached["timestamp"]
                if not isinstance(timestamp, (int, float)):
                    raise ValueError(f"timestamp в кеше должен быть числом, получено {timestamp!r}")
                cached_value = parse(cached["data"])
            except DATA_ERRORS:
                cached = None
            else:
                if time.time() - timestamp < self.ttl:
                    return cached_value
        try:
            response = self.session.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            value = parse(data)
        except (requests.RequestException, *DATA_ERRORS) as exc:
            if cached is not None:
                LOG.warning("Ошибка для %s: %s. Используем устаревший кеш", url, exc)
                return cached_value
            raise ValueError(f"Не удалось получить {url}; кеш пуст: {exc}") from exc
        self.cache[url] = {"timestamp": time.time(), "data": data}
        try:
            write_text(self.cache_file, json.dumps(self.cache, ensure_ascii=False, indent=2))
        except OSError as exc:
            LOG.warning("Не удалось сохранить кеш %s: %s", self.cache_file, exc)
        return value

    def resolve(self, url):
        def parse(data):
            groups = data.values() if isinstance(data, dict) else (data,)
            if not all(isinstance(group, list) for group in groups):
                raise ValueError(f"Ожидался JSON-массив или объект списков, получено {data!r}")
            return string_dict(flatten(groups))

        return self.fetch(url, parse)

    def dns_answers(self, domain, kind):
        url = (
            requests.Request("GET", self.doh_url, params={"name": domain, "type": kind})
            .prepare()
            .url
        )
        record_type = dns.rdatatype.from_text(kind)

        def parse(data):
            if not isinstance(data, dict) or data.get("Status") not in (0, 3):
                raise ValueError(data)
            records = string_dict(
                answer["data"] for answer in data.get("Answer", []) if answer["type"] == record_type
            )
            return dict.fromkeys(
                dns.rdata.from_text(dns.rdataclass.IN, record_type, record) for record in records
            )

        return self.fetch(url, parse)

    def to_ip(self, domains):
        result = {}
        for domain in dict.keys(domains):
            targets = {domain: None}
            targets.update(
                (answer.target.to_text().rstrip("."), None)
                for answer in self.dns_answers(f"_minecraft._tcp.{domain}", "SRV")
            )
            resolved = dict.fromkeys(
                answer.address
                for target in targets
                if target
                for answer in self.dns_answers(target, "A")
            )
            if not resolved:
                LOG.warning("Не найдено IP-адресов для %s", domain)
            result.update(resolved)
        return result


def generate(config, session):
    sources = Sources(config, session)
    env = SandboxedEnvironment(
        autoescape=False, undefined=StrictUndefined, keep_trailing_newline=True, finalize=finalize
    )
    env.intercepted_binops = frozenset({"+"})
    env.binop_table["+"] = dict.__or__
    env.globals.update(resolve=sources.resolve, exclude=exclude, toIp=sources.to_ip)
    return env.from_string(config["rules"]).render(
        lists={name: string_dict(values) for name, values in config.get("lists", {}).items()},
        vars=config.get("vars", {}),
    )


def main():
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    try:
        config = yaml.safe_load(Path(__file__).with_name("config.yml").read_text(encoding="utf-8"))
        with requests.Session() as session:
            rules = generate(config, session)
        write_text("rules", rules)
    except (OSError, *DATA_ERRORS, TemplateError, yaml.YAMLError) as exc:
        LOG.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
