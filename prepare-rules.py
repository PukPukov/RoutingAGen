import json
import socket
import ipaddress
import requests

response_main = requests.get("https://iplist.opencck.org/?format=json&data=domains&wildcard=1&exclude[group]=ai&exclude[group]=casino")
response_main.raise_for_status()
source_main = response_main.content

include = {
    "blancvpn.com",
    "durevpn.com",
    "maximkatz.com",
    "speedtest.net",
    "ooklaserver.net",
    "openjdk.org",
    "arena.ai",
    "bcachefs.org",
    "jsonbeautifier.org",
    "extranix.com",
    "noogle.dev",
    "who.is",
    "canvasmc.io",
}

exclude = {
    "google.com",
}

resolveByIpInclude = {
    "minemalia.net",
    "play.minemalia.net",
}

all_domains_set = set()
all_domains = list()
for domain_list in json.loads(source_main).values():
    for domain in domain_list:
        if domain not in all_domains_set and domain not in exclude:
            all_domains.append(domain)
            all_domains_set.add(domain)
for includum in include:
    all_domains.append(includum)
output = []
output.append("default: direct")
output.append("")
output.append(f"domain({", ".join(all_domains)})->proxy")
output.append("")

response_telegram = requests.get("https://iplist.opencck.org/?format=json&data=cidr4&site=telegram.org")
response_telegram.raise_for_status()
source_telegram = response_telegram.content

all_ips_set = set()
for ip_list in json.loads(source_telegram).values():
    for ip in ip_list:
        all_ips_set.add(ip)
for includum in resolveByIpInclude:
    addrinfo = socket.getaddrinfo(includum, None)
    ips = set(item[4][0] for item in addrinfo)
    for ip in ips:
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.version == 4:
            all_ips_set.add(ip)
output.append(f"ip({", ".join(all_ips_set)})->proxy")

output_merged = "\n".join(output)

with open("rules", "w", encoding="utf-8") as f:
    f.write(output_merged)