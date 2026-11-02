# Развертывание Nextcloud (стек LEMP + SSL) на Ubuntu 24.04

Данное руководство описывает пошаговую установку и настройку облачного хранилища Nextcloud на базе веб-сервера Nginx, СУБД MariaDB и PHP (стек LEMP) в операционной системе Ubuntu 24.04 LTS. 
Для безопасной работы в локальной сети (без доступа извне) настраивается самоподписанный SSL-сертификат.

### Способы установки

В репозитории представлены два способа развертывания стенда:
1. **Ручной (пошаговый)** — подробно описан в данном руководстве ниже (Вариант 1). Позволяет контролировать каждый этап установки и настройки.
2. **Автоматизированный** — для удобства установка вынесена в готовый bash-скрипт `install_nextcloud_lemp.sh` (Вариант 2), который находится в этом репозитории.

## Архитектура стенда

| Хостнейм | IP-адрес (LAN) | Роль | Устанавливаемое ПО |
| :--- | :--- | :--- | :--- |
| LINUX-NEXTCLOUD | 192.168.200.31 | Сервер облачного хранилища | Nginx, MariaDB, PHP 8.3, Nextcloud, OpenSSL |

Инструкция предполагает, что на хосте используется стандартная установка Ubuntu Server 24.04.

---

## Часть 0. Настройка статического IP-адреса (Netplan)

*Этот шаг выполняется вручную в любом случае, так как автоматизация изменения сети может привести к потере SSH-доступа.*

Поскольку адрес `192.168.200.31` был выдан по DHCP, перед установкой Nextcloud необходимо зафиксировать его, чтобы он не изменился после перезагрузки.

1. Посмотрите имя сетевого интерфейса (обычно `enp0s3`, `eth0` и т.д.):
   ```bash
   ip a
   ```
2. Откройте файл конфигурации Netplan:
   ```bash
   sudo nano /etc/netplan/00-installer-config.yaml
   ```
3. Приведите файл к следующему виду (замените `enp0s3` на имя вашего интерфейса; шлюз и DNS — `192.168.200.10`, то есть DC01):
   ```yaml
   network:
     version: 2
     ethernets:
       enp0s3:
         dhcp4: false
         addresses:
           - 192.168.200.31/24
         routes:
           - to: default
             via: 192.168.200.10
         nameservers:
           addresses: [192.168.200.10, 1.1.1.1]
   ```
4. Примените настройки:
   ```bash
   sudo netplan apply
   ```

---

# Вариант 1. Ручная установка (пошаговая)

## Часть 1. Установка стека LEMP

### 1.1 Обновление системы и установка Nginx
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install nginx -y
```

### 1.2 Установка MariaDB
```bash
sudo apt install mariadb-server -y
sudo mysql_secure_installation
```

### 1.3 Установка PHP 8.3 и модулей
```bash
sudo apt install php8.3-fpm php8.3-mysql php8.3-curl php8.3-gd php8.3-mbstring php8.3-xml php8.3-zip php8.3-intl php8.3-bcmath php8.3-imagick php8.3-redis php8.3-apcu -y
```

## Часть 2. Настройка базы данных
1. Войдите в консоль MariaDB:
   ```bash
   sudo mariadb
   ```
2. Создайте базу и пользователя (пароль `ChangeMe_StrongPass!` в примере ниже замените на свой надёжный пароль):
   ```sql
   CREATE DATABASE nextcloud CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
   CREATE USER 'nextcloud'@'localhost' IDENTIFIED BY 'ChangeMe_StrongPass!';
   GRANT ALL PRIVILEGES ON nextcloud.* TO 'nextcloud'@'localhost';
   FLUSH PRIVILEGES;
   EXIT;
   ```

## Часть 3. Установка Nextcloud
```bash
cd /tmp
wget https://download.nextcloud.com/server/releases/latest.zip
sudo apt install unzip -y
sudo unzip latest.zip -d /var/www/html/
sudo chown -R www-data:www-data /var/www/html/nextcloud
sudo chmod -R 755 /var/www/html/nextcloud
```

## Часть 4. Генерация самоподписанного SSL-сертификата
1. Создайте директорию:
   ```bash
   sudo mkdir -p /etc/nginx/ssl
   ```
2. Сгенерируйте ключ и сертификат. В поле `Common Name` обязательно укажите IP: `192.168.200.31`.
   ```bash
   sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
     -keyout /etc/nginx/ssl/nextcloud.key \
     -out /etc/nginx/ssl/nextcloud.crt
   sudo chmod 600 /etc/nginx/ssl/nextcloud.key
   ```

## Часть 5. Настройка Nginx
1. Создайте конфигурационный файл:
   ```bash
   sudo nano /etc/nginx/sites-available/nextcloud
   ```
2. Вставьте конфигурацию:
   ```nginx
   upstream php-handler {
       server unix:/run/php/php8.3-fpm.sock;
   }

   server {
       listen 80;
       listen [::]:80;
       server_name 192.168.200.31;
       return 301 https://$host$request_uri;
   }

   server {
       listen 443 ssl;
       listen [::]:443 ssl;
       server_name 192.168.200.31;

       ssl_certificate /etc/nginx/ssl/nextcloud.crt;
       ssl_certificate_key /etc/nginx/ssl/nextcloud.key;
       ssl_protocols TLSv1.2 TLSv1.3;
       ssl_ciphers HIGH:!aNULL:!MD5;

       root /var/www/html/nextcloud;

       client_max_body_size 512M;
       client_body_timeout 300s;
       fastcgi_buffers 64 4K;

       add_header X-Content-Type-Options nosniff;
       add_header X-Frame-Options "SAMEORIGIN";
       add_header X-XSS-Protection "1; mode=block";
       add_header X-Robots-Tag "noindex, nofollow";

       location / {
           try_files $uri $uri/ /index.php$request_uri;
       }

       location ~ ^/(?:build|tests|config|lib|3rdparty|templates|data)(?:$|/)  { return 404; }
       location ~ ^/(?:\.|autotest|occ|issue|indie|db_|console)                { return 404; }

       location ~ \.php(?:$|/) {
           fastcgi_split_path_info ^(.+?\.php)(/.*)$;
           set $path_info $fastcgi_path_info;
           try_files $fastcgi_script_name =404;
           include fastcgi_params;
           fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
           fastcgi_param PATH_INFO $path_info;
           fastcgi_param HTTPS on;
           fastcgi_param modHeadersAvailable true;
           fastcgi_param front_controller_active true;
           fastcgi_pass php-handler;
           fastcgi_intercept_errors on;
           fastcgi_request_buffering off;
           fastcgi_read_timeout 300;
           fastcgi_send_timeout 300;
       }

       location ~ \.(?:css|js|mjs|svg|gif|png|jpg|ico|wasm|tflite|map|ogg|flac)$ {
           try_files $uri /index.php$request_uri;
           expires 6M;
           access_log off;
       }

       location ~ \.woff2?$ {
           try_files $uri /index.php$request_uri;
           expires 7d;
           access_log off;
       }
   }
   ```
3. Активируйте сайт и перезапустите Nginx:
   ```bash
   sudo ln -s /etc/nginx/sites-available/nextcloud /etc/nginx/sites-enabled/
   sudo rm /etc/nginx/sites-enabled/default
   sudo nginx -t
   sudo systemctl reload nginx
   ```

## Часть 6. Настройка файрвола
```bash
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

## Часть 7. Первичная настройка и Trusted Domains
1. Перейдите в браузере по адресу `https://192.168.200.31` (примите предупреждение сертификата).
2. Заполните данные БД, созданные в Части 2.
3. Если появится ошибка "Untrusted Domain", отредактируйте конфиг:
   ```bash
   sudo nano /var/www/html/nextcloud/config/config.php
   ```
   Добавьте IP в массив и пропишите протокол:
   ```php
     'trusted_domains' => 
     array (
       0 => 'localhost',
       1 => '192.168.200.31',
     ),
     'overwriteprotocol' => 'https',
   ```

---

# Вариант 2. Автоматизированная установка (Bash-скрипт)

Если вы хотите пропустить шаги 1-6, используйте готовый скрипт `install_nextcloud_lemp.sh` из этого репозитория.

### Как использовать скрипт:
1. Скопируйте файл скрипта на сервер (или создайте его через `nano install_nextcloud_lemp.sh`).
2. Пароль базы данных в скрипте не хранится: передайте его через переменную окружения `DB_PASS` либо введите интерактивно при запуске.
3. Сделайте файл исполняемым и запустите от имени root:
   ```bash
   chmod +x install_nextcloud_lemp.sh
   sudo ./install_nextcloud_lemp.sh
   # или сразу с паролем: sudo DB_PASS='ВашПароль' ./install_nextcloud_lemp.sh
   ```
4. После завершения работы скрипта выполните **Часть 7** (веб-настройка в браузере и настройка `trusted_domains`, если потребуется).

<details>
<summary><b>Код скрипта install_nextcloud_lemp.sh (нажмите, чтобы развернуть)</b></summary>

```bash
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
```
</details>

---

## Возможные проблемы и способы их решения

| Проблема | Решение |
| :--- | :--- |
| **Браузер блокирует вход** | Это нормальная реакция на самоподписанный сертификат. Нажмите "Дополнительно" -> "Перейти на сайт (небезопасно)". |
| **Ошибка 504 Gateway Timeout** | Убедитесь, что в конфигурации Nginx есть строки `fastcgi_read_timeout 300;` и `fastcgi_send_timeout 300;`. Проверьте статус PHP-FPM: `systemctl status php8.3-fpm`. |
| **Ошибка "Access denied for user"** | Проверьте, что в MariaDB создан пользователь `nextcloud`@`localhost` и пароль в веб-интерфейсе введен без опечаток. |
| **Nginx выдает "403 Forbidden"** | Проверьте права на папку `/var/www/html/nextcloud`. Владелец — `www-data`, права — `755`. |
| **Ошибка "Untrusted Domain"** | Добавьте IP-адрес сервера в массив `trusted_domains` в файле `/var/www/html/nextcloud/config/config.php`. |
