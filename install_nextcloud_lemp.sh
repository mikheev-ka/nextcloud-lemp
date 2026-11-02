#!/bin/bash

# ==============================================================================
# Скрипт автоматической установки Nextcloud (LEMP + Self-Signed SSL)
# ОС: Ubuntu 24.04 LTS
# ==============================================================================

set -e # Остановить выполнение при любой ошибке

# --- Переменные ---
SERVER_IP="192.168.200.31" 
DB_NAME="nextcloud"
DB_USER="nextcloud"
NC_DIR="/var/www/html/nextcloud"
SSL_DIR="/etc/nginx/ssl"

# Пароль БД не хранится в скрипте: передайте его через переменную окружения
# (sudo DB_PASS='ВашПароль' ./install_nextcloud_lemp.sh) или введите при запросе.
DB_PASS="${DB_PASS:-}"
if [ -z "$DB_PASS" ]; then
  read -rsp "Введите пароль для пользователя БД '${DB_USER}': " DB_PASS
  echo
fi
if [ -z "$DB_PASS" ]; then
  echo "Ошибка: пароль БД не задан."
  exit 1
fi

# Проверка, что скрипт запущен от root
if [ "$EUID" -ne 0 ]; then
  echo "Пожалуйста, запустите скрипт от имени root (sudo ./install_nextcloud_lemp.sh)"
  exit 1
fi

echo "=== 1. Обновление системы и установка пакетов ==="
apt-get update && apt-get upgrade -y
export DEBIAN_FRONTEND=noninteractive
apt-get install -y nginx mariadb-server unzip wget openssl ufw \
    php8.3-fpm php8.3-mysql php8.3-curl php8.3-gd php8.3-mbstring \
    php8.3-xml php8.3-zip php8.3-intl php8.3-bcmath php8.3-imagick \
    php8.3-redis php8.3-apcu

echo "=== 2. Настройка базы данных MariaDB ==="
mariadb -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"
mariadb -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';"
mariadb -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
mariadb -e "FLUSH PRIVILEGES;"

echo "=== 3. Загрузка и распаковка Nextcloud ==="
cd /tmp
wget -q https://download.nextcloud.com/server/releases/latest.zip
unzip -q latest.zip -d /var/www/html/
chown -R www-data:www-data ${NC_DIR}
chmod -R 755 ${NC_DIR}

echo "=== 4. Генерация самоподписанного SSL-сертификата ==="
mkdir -p ${SSL_DIR}
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ${SSL_DIR}/nextcloud.key \
  -out ${SSL_DIR}/nextcloud.crt \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Lab/OU=IT/CN=${SERVER_IP}"
chmod 600 ${SSL_DIR}/nextcloud.key

echo "=== 5. Настройка конфигурации Nginx ==="
cat <<EOF > /etc/nginx/sites-available/nextcloud
upstream php-handler {
    server unix:/run/php/php8.3-fpm.sock;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_IP};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name ${SERVER_IP};

    ssl_certificate ${SSL_DIR}/nextcloud.crt;
    ssl_certificate_key ${SSL_DIR}/nextcloud.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    root ${NC_DIR};
    client_max_body_size 512M;
    client_body_timeout 300s;
    fastcgi_buffers 64 4K;

    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-XSS-Protection "1; mode=block";
    add_header X-Robots-Tag "noindex, nofollow";

    location / {
        try_files \$uri \$uri/ /index.php\$request_uri;
    }

    location ~ ^/(?:build|tests|config|lib|3rdparty|templates|data)(?:\$|/)  { return 404; }
    location ~ ^/(?:\.|autotest|occ|issue|indie|db_|console)                { return 404; }

    location ~ \.php(?:\$|/) {
        fastcgi_split_path_info ^(.+?\.php)(/.*)\$;
        set \$path_info \$fastcgi_path_info;
        try_files \$fastcgi_script_name =404;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME \$document_root\$fastcgi_script_name;
        fastcgi_param PATH_INFO \$path_info;
        fastcgi_param HTTPS on;
        fastcgi_param modHeadersAvailable true;
        fastcgi_param front_controller_active true;
        fastcgi_pass php-handler;
        fastcgi_intercept_errors on;
        fastcgi_request_buffering off;
        fastcgi_read_timeout 300;
        fastcgi_send_timeout 300;
    }

    location ~ \.(?:css|js|mjs|svg|gif|png|jpg|ico|wasm|tflite|map|ogg|flac)\$ {
        try_files \$uri /index.php\$request_uri;
        expires 6M;
        access_log off;
    }

    location ~ \.woff2?\$ {
        try_files \$uri /index.php\$request_uri;
        expires 7d;
        access_log off;
    }
}
EOF

ln -sf /etc/nginx/sites-available/nextcloud /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx
systemctl restart php8.3-fpm

echo "=== 6. Настройка файрвола UFW ==="
ufw allow 'Nginx Full'
ufw allow OpenSSH
ufw --force enable

echo "=============================================================================="
echo "Установка успешно завершена!"
echo "Перейдите в браузере по адресу: https://${SERVER_IP}"
echo "Данные для подключения к БД:"
echo "Логин: ${DB_USER} | Пароль: ${DB_PASS} | БД: ${DB_NAME} | Хост: localhost"
echo "=============================================================================="