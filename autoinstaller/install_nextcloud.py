#!/usr/bin/env python3
"""
Автоматическая установка Nextcloud на LEMP (Ubuntu 24.04) с самоподписанным SSL.
Запуск: sudo python3 install_nextcloud.py
"""

import os
import sys
import subprocess
import shlex
from pathlib import Path

# ---------- НАСТРОЙКИ (измените под свою среду) ----------
SERVER_IP = "192.168.24.187"
DB_NAME = "nextcloud"
DB_USER = "nextclouduser"
DB_PASS = "StrongPassword123!"
ADMIN_USER = "admin"
ADMIN_PASS = "SuperSecretPass456!"
PHP_VERSION = "8.3"
NEXTCLOUD_DIR = Path("/var/www/nextcloud")
MEMORY_LIMIT = "512M"
UPLOAD_MAX = "500M"
POST_MAX = "500M"
# ----------------------------------------------------------------

def run_command(cmd, check=True, shell=False, env=None):
    """Выполнить команду, выводя её в консоль. Выход с ошибкой при check=True."""
    if shell and isinstance(cmd, list):
        cmd = " ".join(shlex.quote(str(arg)) for arg in cmd)
    elif not shell and isinstance(cmd, str):
        cmd = shlex.split(cmd)
    print(f"  RUN: {cmd}")
    subprocess.run(cmd, check=check, shell=shell, env=env)

def run_shell(cmd):
    """Выполнить shell-команду."""
    run_command(cmd, shell=True)

def check_root():
    if os.geteuid() != 0:
        sys.exit("Ошибка: скрипт должен запускаться от root (sudo python3 ...)")

def install_system_packages():
    print("\n=== Обновление системы и установка базовых пакетов ===")
    run_shell("apt update && apt upgrade -y")
    run_shell("apt install -y nginx mariadb-server mariadb-client unzip wget curl software-properties-common")

def install_php():
    print("\n=== Установка PHP 8.3 ===")
    run_shell("add-apt-repository -y ppa:ondrej/php")
    run_shell("apt update")
    php_packages = [
        f"php{PHP_VERSION}-fpm",
        f"php{PHP_VERSION}-mysql",
        f"php{PHP_VERSION}-curl",
        f"php{PHP_VERSION}-gd",
        f"php{PHP_VERSION}-mbstring",
        f"php{PHP_VERSION}-xml",
        f"php{PHP_VERSION}-zip",
        f"php{PHP_VERSION}-intl",
        f"php{PHP_VERSION}-bcmath",
        f"php{PHP_VERSION}-gmp",
        f"php{PHP_VERSION}-imagick",
    ]
    run_command(["apt", "install", "-y"] + php_packages)

def configure_mariadb():
    print("\n=== Настройка MariaDB ===")
    run_shell("systemctl enable --now mariadb")
    queries = [
        "DELETE FROM mysql.user WHERE User='';",
        "DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');",
        "DROP DATABASE IF EXISTS test;",
        "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';",
        "FLUSH PRIVILEGES;",
        f"CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;",
        f"CREATE USER IF NOT EXISTS '{DB_USER}'@'localhost' IDENTIFIED BY '{DB_PASS}';",
        f"GRANT ALL PRIVILEGES ON {DB_NAME}.* TO '{DB_USER}'@'localhost';",
        "FLUSH PRIVILEGES;",
    ]
    for query in queries:
        run_command(["mysql", "-u", "root", "-e", query])

def download_nextcloud():
    print("\n=== Скачивание и распаковка Nextcloud ===")
    zip_path = "/tmp/nextcloud.zip"
    run_shell(f"wget -q https://download.nextcloud.com/server/releases/latest.zip -O {zip_path}")
    run_shell(f"unzip -qo {zip_path} -d /var/www/")
    NEXTCLOUD_DIR.mkdir(parents=True, exist_ok=True)
    run_shell(f"chown -R www-data:www-data {NEXTCLOUD_DIR}")

def sed_replace(filepath, pattern, replacement):
    """
    Выполняет замену sed в файле.
    Автоматически выбирает разделитель: '/' если в replacement нет '/', иначе '#'.
    """
    if "/" in replacement:
        sep = "#"
    else:
        sep = "/"
    # Экранируем возможные спецсимволы в pattern (очень просто, только для '/')
    safe_pattern = pattern.replace("/", r"\/")
    cmd = f"sed -i 's{sep}{safe_pattern}{sep}{replacement}{sep}' {filepath}"
    run_shell(cmd)

def configure_php():
    print("\n=== Настройка PHP ===")
    php_ini = f"/etc/php/{PHP_VERSION}/fpm/php.ini"
    replacements = {
        r"^memory_limit = .*": MEMORY_LIMIT,
        r"^upload_max_filesize = .*": UPLOAD_MAX,
        r"^post_max_size = .*": POST_MAX,
        r"^max_execution_time = .*": "300",
        r"^;date.timezone =.*": "Europe/Moscow",
        r";opcache.enable=1": "1",          # значение opcache.enable=1 уже включает, но строка может быть закомментирована
        r";opcache.memory_consumption=128": "128",
        r";opcache.max_accelerated_files=10000": "10000",
        r";opcache.revalidate_freq=1": "1",
    }
    for pattern, value in replacements.items():
        sed_replace(php_ini, pattern, f"{pattern.split()[-1]} = {value}" if "=" in pattern else value)
        # Для опций без '=' (opcache) нужно более аккуратно, поэтому чуть упростим.
        # Но в текущем виде pattern содержит '=' только у не-опкешных, у опкешных после точки значение.
        # Лучше использовать точные шаблоны с захватом. Упростим: будем подставлять полную строку.
        # Перепишем replacements в более понятном виде.
    # Более надёжный способ (перезапишем функцию ниже)

def configure_php_refactored():
    """Переработанная настройка PHP с точными заменами."""
    php_ini = Path(f"/etc/php/{PHP_VERSION}/fpm/php.ini")
    lines_to_set = {
        "memory_limit": MEMORY_LIMIT,
        "upload_max_filesize": UPLOAD_MAX,
        "post_max_size": POST_MAX,
        "max_execution_time": "300",
        "date.timezone": "Europe/Moscow",
        "opcache.enable": "1",
        "opcache.memory_consumption": "128",
        "opcache.max_accelerated_files": "10000",
        "opcache.revalidate_freq": "1",
    }
    for key, value in lines_to_set.items():
        # Экранируем ключ для sed
        # Если строка начинается с ';' или без неё, заменяем всю строку.
        sed_replace(php_ini, rf"^;?\s*{key}\s*=.*", f"{key} = {value}")

def generate_selfsigned_cert():
    print("\n=== Генерация самоподписанного SSL-сертификата ===")
    cert_dir = Path("/etc/nginx/ssl")
    cert_dir.mkdir(parents=True, exist_ok=True)
    run_shell(
        f"openssl req -x509 -nodes -days 3650 -newkey rsa:2048 "
        f"-keyout {cert_dir}/nextcloud.key "
        f"-out {cert_dir}/nextcloud.crt "
        f"-subj '/CN={SERVER_IP}'"
    )

def write_nginx_config():
    print("\n=== Создание конфигурации Nginx ===")
    nginx_conf = f"""
server {{
    listen 80;
    listen [::]:80;
    server_name {SERVER_IP};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name {SERVER_IP};

    ssl_certificate     /etc/nginx/ssl/nextcloud.crt;
    ssl_certificate_key /etc/nginx/ssl/nextcloud.key;

    root {NEXTCLOUD_DIR};
    client_max_body_size {UPLOAD_MAX};
    fastcgi_buffers 64 4K;

    location / {{
        rewrite ^ /index.php;
    }}

    location ~ ^/(?:build|tests|config|lib|3rdparty|templates|data)/ {{ deny all; }}
    location ~ ^/(?:\\.|autotest|occ|issue|indie|db_|console) {{ deny all; }}

    location ~ ^/(?:index|remote|public|cron|core/ajax/update|status|ocs/v[12]|updater/.+|oc[ms]-provider/.+)\\.php(?:$|/) {{
        fastcgi_split_path_info ^(.+?\\.php)(/.*)$;
        set $path_info $fastcgi_path_info;
        try_files $fastcgi_script_name =404;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param PATH_INFO $path_info;
        fastcgi_pass unix:/var/run/php/php{PHP_VERSION}-fpm.sock;
        fastcgi_intercept_errors on;
    }}

    location ~* \\.(?:css|js|woff2?|svg|gif|png|jpg|ico)$ {{
        try_files $uri /index.php$request_uri;
        expires 6M;
        access_log off;
        add_header Cache-Control "public, immutable";
    }}
}}
"""
    conf_path = Path("/etc/nginx/sites-available/nextcloud")
    conf_path.write_text(nginx_conf)
    # Активация
    default_conf = Path("/etc/nginx/sites-enabled/default")
    if default_conf.exists():
        default_conf.unlink()
    enabled_link = Path("/etc/nginx/sites-enabled/nextcloud")
    if not enabled_link.exists():
        enabled_link.symlink_to(conf_path)
    run_shell("nginx -t && systemctl reload nginx")

def install_nextcloud():
    print("\n=== Финальная установка Nextcloud через occ ===")
    occ_bin = NEXTCLOUD_DIR / "occ"
    if not occ_bin.exists():
        sys.exit("Ошибка: occ не найден. Проверьте установку Nextcloud.")
    run_command([
        "sudo", "-u", "www-data", "php", str(occ_bin),
        "maintenance:install",
        "--database", "mysql",
        "--database-name", DB_NAME,
        "--database-user", DB_USER,
        "--database-pass", DB_PASS,
        "--admin-user", ADMIN_USER,
        "--admin-pass", ADMIN_PASS,
        "--data-dir", str(NEXTCLOUD_DIR / "data")
    ])
    # trusted_domains
    run_command([
        "sudo", "-u", "www-data", "php", str(occ_bin),
        "config:system:set", "trusted_domains", "0", "--value", SERVER_IP
    ])

def setup_cron():
    print("\n=== Настройка Cron ===")
    cron_line = f"*/5 * * * * php -f {NEXTCLOUD_DIR}/cron.php"
    run_shell(f"(crontab -u www-data -l 2>/dev/null; echo '{cron_line}') | crontab -u www-data -")

def configure_firewall():
    print("\n=== Настройка файрвола ===")
    run_shell("ufw allow 80/tcp")
    run_shell("ufw allow 443/tcp")
    run_shell("ufw --force enable")

def main():
    check_root()
    install_system_packages()
    install_php()
    configure_mariadb()
    download_nextcloud()
    configure_php_refactored()   # обновлённая версия
    generate_selfsigned_cert()
    write_nginx_config()
    install_nextcloud()
    setup_cron()
    configure_firewall()

    print("\n" + "=" * 60)
    print(" Установка Nextcloud завершена!")
    print(f" Доступ:  https://{SERVER_IP}")
    print(f" Логин:   {ADMIN_USER}")
    print(f" Пароль:  {ADMIN_PASS}")
    print(" Сертификат самоподписанный – примите исключение в браузере.")
    print("=" * 60)

if __name__ == "__main__":
    main()