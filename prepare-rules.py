import json
import os
import time
import requests
import yaml
from pathlib import Path

class CacheManager:
    """Управляет чтением и записью в файл .cache"""
    def __init__(self, cache_file):
        self.cache_file = cache_file
        self.cache_data = self._load_cache()

    def _load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def save_cache(self):
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache_data, f, ensure_ascii=False, indent=2)

    def get(self, key):
        return self.cache_data.get(key)

    def set(self, key, data):
        self.cache_data[key] = {
            'timestamp': time.time(),
            'data': data
        }
        self.save_cache()


def fetch_json_with_cache(url, cache_manager: CacheManager, ttl: int, timeout=5):
    """Делает GET запрос ожидая JSON. При успехе пишет в кеш. При ошибке берет из кеша."""
    cached = cache_manager.get(url)
    now = time.time()

    if cached and (now - cached['timestamp'] < ttl):
        return cached['data']

    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        cache_manager.set(url, data)
        return data
    except Exception as e:
        if cached:
            print(f"[WARN] Ошибка для {url}: {e}. Используем устаревший кеш.")
            return cached['data']
        
        print(f"[ERROR] Не удалось получить данные для {url} и кеш пуст. Ошибка: {e}")
        return None


def read_filter_file(filename):
    """Читает файл построчно, игнорируя комментарии и пустые строки"""
    filepath = Path('filters') / filename
    items = set()
    
    if not filepath.exists():
        print(f"[WARN] Файл {filepath} не найден. Пропускаем.")
        return items
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                items.add(line)
    return items


def resolve_ips_for_domain(domain, cache_manager, ttl, doh_url):
    """Выполняет DNS запросы (SRV и A) через DoH, возвращает множество IP-адресов"""
    resolved_ips = set()
    resolved = False
    
    # 1. Запрос SRV
    srv_url = f"{doh_url}?name=_minecraft._tcp.{domain}&type=SRV"
    srv_data = fetch_json_with_cache(srv_url, cache_manager, ttl)
    
    if srv_data and "Answer" in srv_data:
        for answer in srv_data["Answer"]:
            if answer["type"] == 33:  # SRV
                target_domain = answer["data"].split()[-1].rstrip('.')
                a_url = f"{doh_url}?name={target_domain}&type=A"
                a_data = fetch_json_with_cache(a_url, cache_manager, ttl)
                
                if a_data and "Answer" in a_data:
                    for a_answer in a_data["Answer"]:
                        if a_answer["type"] == 1:  # IPv4
                            resolved_ips.add(a_answer["data"])
                            resolved = True

    # 2. Запрос A записи напрямую
    a_url = f"{doh_url}?name={domain}&type=A"
    a_data = fetch_json_with_cache(a_url, cache_manager, ttl)
    
    if a_data and "Answer" in a_data:
        for answer in a_data["Answer"]:
            if answer["type"] == 1:  # IPv4
                resolved_ips.add(answer["data"])
                resolved = True

    return resolved_ips, resolved


def main():
    if not os.path.exists("config.yml"):
        print("[ERROR] Файл config.yml не найден! Завершение работы.")
        return

    with open("config.yml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    Path("filters").mkdir(exist_ok=True)

    ttl = config['cache']['ttl_seconds']
    doh_url = config.get('dns', {}).get('doh_url', 'https://dns.google/resolve')
    cache_manager = CacheManager(config['cache']['file'])

    include = read_filter_file('include.txt')
    exclude = read_filter_file('exclude.txt')
    resolve_by_ip_include = read_filter_file('resolveByIpInclude.txt')

    output = []
    output.append("default: direct")

    # --- 1. Обработка доменов OpenCCK ---
    source_main = fetch_json_with_cache(config['opencck']['main'], cache_manager, ttl)
    
    # Оригинальная логика сохранения порядка через set + list
    all_domains_set = set()
    all_domains = list()
    
    if source_main:
        for domain_list in source_main.values():
            for domain in domain_list:
                if domain not in all_domains_set and domain not in exclude:
                    all_domains.append(domain)
                    all_domains_set.add(domain)

    for includum in include:
        if includum not in all_domains_set:
            all_domains.append(includum)
            all_domains_set.add(includum)

    output.append(f"domain({", ".join(all_domains)})->proxy")

    # --- 2. Обработка IP Telegram ---
    source_telegram = fetch_json_with_cache(config['opencck']['telegram'], cache_manager, ttl)
    all_ips_set = set()
    
    if source_telegram:
        for ip_list in source_telegram.values():
            for ip in ip_list:
                all_ips_set.add(ip)

    # --- 3. Разрешение IP через вынесенную функцию ---
    for includum in resolve_by_ip_include:
        resolved_ips, was_resolved = resolve_ips_for_domain(includum, cache_manager, ttl, doh_url)
        
        if was_resolved:
            all_ips_set.update(resolved_ips)
        else:
            print(f"[WARN] Не найдено IP-адресов для {includum}")

    output.append(f"ip({", ".join(all_ips_set)})->proxy")

    # --- 4. Финализация ---
    output_merged = "\n".join(output)
    with open("rules", "w", encoding="utf-8") as f:
        f.write(output_merged)
    
    print("Генерация файла rules успешно завершена.")

if __name__ == "__main__":
    main()