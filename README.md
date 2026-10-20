# Развертывание Nextcloud (стек LEMP) на Ubuntu 24.04

Данное руководство описывает пошаговую установку и настройку облачного хранилища Nextcloud на базе веб-сервера Nginx, СУБД MariaDB и PHP (стек LEMP) в операционной системе Ubuntu 24.04 LTS.

### Способы установки

В репозитории представлены два способа развертывания стенда:
1. **Ручной (пошаговый)** — подробно описан в данном руководстве ниже. Позволяет контролировать каждый этап установки и настройки.
2. **Автоматизированный** — для удобства установка дополнительно вынесена в готовый bash-скрипт, который находится в репозитории:
   * `install_nextcloud_lemp.sh` — автоматическая установка всех компонентов, настройка БД, генерация SSL и настройка веб-сервера.

## Архитектура стенда

| Хостнейм | IP-адрес (LAN) | Роль | Устанавливаемое ПО |
| :--- | :--- | :--- | :--- |
| LINUX-NEXTCLOUD | 192.168.200.31 | Сервер облачного хранилища | Nginx, MariaDB, PHP 8.3, Nextcloud, OpenSSL |

Инструкция предполагает, что на хосте используется стандартная установка Ubuntu Server 24.04. 

---

## Часть 0. Настройка статического IP-адреса (Netplan)

Поскольку адрес `192.168.200.31` был выдан по DHCP, перед установкой Nextcloud необходимо зафиксировать его, чтобы он не изменился после перезагрузки.

1. Посмотрите имя сетевого интерфейса (обычно `enp0s3`, `eth0` и т.д.):
```bash
ip a
```

2. Откройте файл конфигурации Netplan (имя файла может отличаться, проверьте `ls /etc/netplan/`):
```bash
sudo nano /etc/netplan/00-installer-config.yaml
```

3. Приведите файл к следующему виду (замените `enp0s3` на имя вашего интерфейса, а `192.168.200.1` на шлюз вашей сети, если он отличается):
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
          via: 192.168.200.1
      nameservers:
        addresses: [192.168.200.10, 8.8.8.8] # 192.168.200.10 - ваш DC01 (DNS)
```

4. Примените настройки:
```bash
sudo netplan apply
```

---

## Часть 1. Установка стека LEMP

Подключитесь к серверу 192.168.200.31.

### 1.1 Обновление системы и установка Nginx
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install nginx -y
```
Проверьте, что Nginx запущен:
```bash
sudo systemctl status nginx
```

### 1.2 Установка MariaDB
```bash
sudo apt install mariadb-server -y
```
Запустите скрипт первичной безопасности (задайте root-пароль, удалите анонимных пользователей и т.д.):
```bash
sudo mysql_secure_installation
```

### 1.3 Установка PHP 8.3 и необходимых модулей
Для Nextcloud требуется PHP 8.3 (стандарт для Ubuntu 24.04) и ряд дополнительных расширений:
```bash
sudo apt install php8.3-fpm php8.3-mysql php8.3-curl php8.3-gd php8.3-mbstring php8.3-xml php8.3-zip php8.3-intl php8.3-bcmath php8.3-imagick php8.3-redis php8.3-apcu -y
```

---

## Часть 2. Настройка базы данных для Nextcloud

1. Войдите в консоль MariaDB под пользователем root:
```bash
sudo mariadb
```

2. Выполните SQL-команды для создания базы и пользователя (замените `StrongPassword123!` на свой надежный пароль):
```sql
CREATE DATABASE nextcloud CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE USER 'nextcloud'@'localhost' IDENTIFIED BY 'StrongPassword123!';
GRANT ALL PRIVILEGES ON nextcloud.* TO 'nextcloud'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

---

## Часть 3. Установка Nextcloud

### 3.1 Загрузка и распаковка
Скачайте актуальную версию Nextcloud в директорию `/tmp`:
```bash
cd /tmp
wget https://download.nextcloud.com/server/releases/latest.zip
sudo apt install unzip -y
sudo unzip latest.zip -d /var/www/html/
```

### 3.2 Настройка прав доступа
Передайте права на директорию пользователю веб-сервера (`www-data`):
```bash
sudo chown -R www-data:www-data /var/www/html/nextcloud
sudo chmod -R 755 /var/www/html/nextcloud
```

---

## Часть 4. Генерация самоподписанного SSL-сертификата

Так как доступ извне не планируется, мы создадим самоподписанный сертификат. Браузеры будут выдавать предупреждение о безопасности, но для лабораторного стенда это нормально.

1. Создайте директорию для сертификатов:
```bash
sudo mkdir -p /etc/nginx/ssl
```

2. Сгенерируйте приватный ключ и сертификат (сроком на 365 дней):
```bash
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/nextcloud.key \
  -out /etc/nginx/ssl/nextcloud.crt
```

3. В процессе генерации система задаст несколько вопросов. Самое важное — **Common Name (e.g. server FQDN or YOUR name)**. Введите туда IP-адрес вашего сервера: `192.168.200.31`. Остальные поля (Country, State, Organization) можно заполнить произвольно или оставить пустыми (нажав Enter).

4. Ограничьте права доступа к ключу:
```bash
sudo chmod 600 /etc/nginx/ssl/nextcloud.key
```

---

## Часть 5. Настройка Nginx для Nextcloud с поддержкой HTTPS

1. Создайте конфигурационный файл виртуального хоста:
```bash
sudo nano /etc/nginx/sites-available/nextcloud
```

2. Вставьте следующую конфигурацию. Обратите внимание: мы добавили блок для перенаправления HTTP на HTTPS и настроили SSL:

```nginx
upstream php-handler {
    server unix:/run/php/php8.3-fpm.sock;
}

# Редирект с HTTP на HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name 192.168.200.31;
    return 301 https://$host$request_uri;
}

# Основной блок HTTPS
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name 192.168.200.31;

    # Настройки SSL
    ssl_certificate /etc/nginx/ssl/nextcloud.crt;
    ssl_certificate_key /etc/nginx/ssl/nextcloud.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Путь к установке Nextcloud
    root /var/www/html/nextcloud;

    # Максимальный размер загружаемых файлов (настройте под себя)
    client_max_body_size 512M;
    client_body_timeout 300s;
    fastcgi_buffers 64 4K;

    # Заголовки безопасности
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-XSS-Protection "1; mode=block";
    add_header X-Robots-Tag "noindex, nofollow";

    # Основные настройки
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
        fastcgi_param HTTPS on; # Важно! Теперь HTTPS включен
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

3. Активируйте сайт и отключите дефолтный конфиг Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/nextcloud /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
```

4. Проверьте конфигурацию на ошибки и перезапустите Nginx:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## Часть 6. Настройка файрвола UFW

Откройте порты для веб-сервера (Nginx Full открывает сразу 80 и 443 порты):
```bash
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

---

## Часть 7. Первичная веб-настройка Nextcloud

1. Откройте браузер на вашей хостовой машине и перейдите по адресу: `https://192.168.200.31`
2. Браузер выдаст предупреждение о самоподписанном сертификате ("Ваше подключение не защищено"). Нажмите **"Дополнительно"** -> **"Перейти на 192.168.200.31 (небезопасно)"**.
3. Заполните форму первичной настройки:
   * **Создать учетную запись администратора**: придумайте логин и пароль.
   * **Хранилище и база данных**: нажмите на выпадающий список и выберите **MySQL/MariaDB**.
   * **Логин базы данных**: `nextcloud`
   * **Пароль базы данных**: `StrongPassword123!` (тот, что вы создали в Части 2).
   * **Имя базы данных**: `nextcloud`
   * **Хост базы данных**: `localhost`
4. Нажмите **Установить**.

После завершения установки вы попадете на рабочий стол Nextcloud.

---

## Часть 8. Настройка доверенных доменов (Trusted Domains)

Если Nextcloud будет ругаться на недоверенный домен (что часто бывает при доступе по IP), вам нужно добавить IP в конфигурацию.

1. Откройте файл конфигурации:
```bash
sudo nano /var/www/html/nextcloud/config/config.php
```

2. Найдите массив `trusted_domains` и убедитесь, что там есть ваш IP (или добавьте его):
```php
  'trusted_domains' => 
  array (
    0 => 'localhost',
    1 => '192.168.200.31',
  ),
```

3. (Опционально) Рекомендуется также добавить параметр `overwriteprotocol`, чтобы Nextcloud корректно генерировал ссылки с `https://`:
```php
  'overwriteprotocol' => 'https',
```

---

## Возможные проблемы и способы их решения

| Проблема | Решение |
| :--- | :--- |
| Ошибка 504 Gateway Timeout при установке | Убедитесь, что в конфигурации Nginx (секция `location ~ \.php`) присутствуют строки `fastcgi_read_timeout 300;` и `fastcgi_send_timeout 300;`. Также проверьте, что PHP-FPM запущен (`systemctl status php8.3-fpm`). |
| Ошибка "Access denied for user 'nextcloud'@'localhost'" | Проверьте, что в MariaDB создан именно пользователь `nextcloud` с хоста `localhost`, и пароль в веб-интерфейсе введен без опечаток. |
| Nginx выдает "403 Forbidden" | Проверьте права на папку `/var/www/html/nextcloud`. Владельцем обязательно должен быть пользователь `www-data`, а права на директорию — не менее `755`. |
| Ошибка "Доступ запрещен" или "Домен не доверенный" | Отредактируйте файл `/var/www/html/nextcloud/config/config.php` и добавьте IP-адрес сервера в массив `trusted_domains`. |
| Браузер блокирует вход | Это нормальная реакция на самоподписанный сертификат. Нажмите "Дополнительно" и разрешите переход. Чтобы избавиться от предупреждения, можно импортировать сертификат `/etc/nginx/ssl/nextcloud.crt` в хранилище доверенных сертификатов вашей ОС (на хосте). |
