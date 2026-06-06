# 🛠️ Ручная установка Nextcloud на LEMP (Ubuntu 24.04 LTS)

Пошаговое руководство по самостоятельной ручной настройке облачного хранилища [Nextcloud](https://nextcloud.com) в стеке **LEMP** (**L**inux, **E**nginx, **M**ariaDB, **P**HP 8.3) с защитой трафика через самоподписанный SSL-сертификат.

> [!NOTE]
> Данная инструкция идеально подходит для развертывания локальной виртуальной машины (например, в VirtualBox), тестового стенда или домашнего сервера.

---

## Исходные данные (Пример стенда)

Перед началом установки определитесь с сетевыми параметрами. В данном руководстве используются следующие значения:
* **Хост/Виртуализация**: VirtualBox (сетевой интерфейс в режиме «Сетевой мост»)
* **Локальная подсеть**: `192.168.24.0/24`
* **Основной шлюз**: `192.168.24.1`
* **Статический IP сервера**: `192.168.24.11` *(замените на свой)*
* **Версия PHP**: 8.3

---

## Пошаговая инструкция по установке

### Шаг 1. Настройка статического IP (Netplan)
Для надежной работы сервера зафиксируйте его сетевой адрес. Отредактируйте конфигурационный файл:
```bash
sudo nano /etc/netplan/00-installer-config.yaml
```

Приведите файл к следующему виду (соблюдайте отступы в 2 или 4 пробела, знаки табуляции использовать запрещено):
```yaml
network:
  version: 2
  ethernets:
    enp0s3:
      addresses:
        - 192.168.24.11/24
      routes:
        - to: default
          via: 192.168.24.1
      nameservers:
        addresses:
          - 8.8.8.8
          - 8.8.4.4
```
Примените изменения конфигурации сети:
```bash
sudo netplan apply
```

---

### Шаг 2. Установка базового стека LEMP
Обновите индексы пакетов и установите веб-сервер, базу данных и вспомогательные утилиты:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y nginx mariadb-server mariadb-client unzip wget curl software-properties-common
```

#### Добавление репозитория и установка PHP 8.3
Для Ubuntu 24.04 рекомендуется использовать проверенный PPA-репозиторий от Ondřej Surý:
```bash
sudo add-apt-repository -y ppa:ondrej/php
sudo apt update
sudo apt install -y php8.3-fpm php8.3-mysql php8.3-curl php8.3-gd \
  php8.3-mbstring php8.3-xml php8.3-zip php8.3-intl php8.3-bcmath \
  php8.3-gmp php8.3-imagick
```

Активируйте автоматический запуск всех служб при загрузке системы:
```bash
sudo systemctl enable --now nginx mariadb php8.3-fpm
```

---

### Шаг 3. Первичная настройка СУБД MariaDB
Запустите интерактивный скрипт для базовой защиты базы данных:
```bash
sudo mysql_secure_installation
```
*(Задайте пароль суперпользователя root для БД, удалите анонимных пользователей, запретите удаленный вход для root и удалите тестовую базу данных).*

#### Создание базы данных для Nextcloud
Войдите в консоль MariaDB под администратором:
```bash
sudo mysql
```
Выполните следующие SQL-запросы для создания изолированной базы данных и пользователя:
```sql
CREATE DATABASE nextcloud CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE USER 'nextclouduser'@'localhost' IDENTIFIED BY 'StrongPassword123!';
GRANT ALL PRIVILEGES ON nextcloud.* TO 'nextclouduser'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```
> [!IMPORTANT]
> Замените `StrongPassword123!` на ваш собственный секретный пароль.

---

### Шаг 4. Загрузка и размещение Nextcloud
Скачайте актуальный стабильный релиз с официального сайта, распакуйте его в рабочую директорию веб-сервера и передайте права пользователю `www-data`:
```bash
cd /tmp
wget https://download.nextcloud.com/server/releases/latest.zip
sudo unzip latest.zip -d /var/www/
sudo chown -R www-data:www-data /var/www/nextcloud
```

---

### Шаг 5. Оптимизация параметров PHP 8.3
Для стабильной обработки больших файлов и тяжелых скриптов необходимо скорректировать дефолтные лимиты PHP. Откройте конфигурационный файл:
```bash
sudo nano /etc/php/8.3/fpm/php.ini
```

Найдите (используйте `Ctrl + W` для поиска в nano) и измените значения следующих параметров:
```ini
memory_limit = 512M
upload_max_filesize = 500M
post_max_size = 500M
max_execution_time = 300
date.timezone = Europe/Moscow
opcache.enable=1
opcache.memory_consumption=128
opcache.max_accelerated_files=10000
opcache.revalidate_freq=1
```
Примените настройки перезапуском обработчика процессов:
```bash
sudo systemctl restart php8.3-fpm
```

---

### Шаг 6. Генерация самоподписанного SSL-сертификата
Создайте директорию для хранения ключей и сгенерируйте пару (сертификат + приватный ключ) со сроком действия 10 лет (3650 дней):
```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/nextcloud.key \
  -out /etc/nginx/ssl/nextcloud.crt \
  -subj "/CN=192.168.24.11"
```

---

### Шаг 7. Конфигурация веб-сервера Nginx
Создайте новый файл конфигурации виртуального хоста для вашего облака:
```bash
sudo nano /etc/nginx/sites-available/nextcloud
```

Вставьте в него следующий полноценный конфиг:
```nginx
server {
    listen 80;
    listen [::]:80;
    server_name 192.168.24.11;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name 192.168.24.11;

    # Включение HTTP/2 для современных версий Nginx
    http2 on;

    ssl_certificate     /etc/nginx/ssl/nextcloud.crt;
    ssl_certificate_key /etc/nginx/ssl/nextcloud.key;

    root /var/www/nextcloud;
    client_max_body_size 500M;
    fastcgi_buffers 64 4K;

    # Настройка заголовков безопасности (HSTS)
    add_header Strict-Transport-Security "max-age=15552000; includeSubDomains" always;

    location / {
        rewrite ^ /index.php;
    }

    location ~ ^/(?:build|tests|config|lib|3rdparty|templates|data)/ { deny all; }
    location ~ ^/(?:\.|autotest|occ|issue|indie|db_|console) { deny all; }

    location ~ ^/(?:index|remote|public|cron|core/ajax/update|status|ocs/v[12]|updater/.+|oc[ms]-provider/.+)\.php(?:$|/) {
        fastcgi_split_path_info ^(.+?\.php)(/.*)$;
        set $path_info $fastcgi_path_info;
        try_files $fastcgi_script_name =404;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param PATH_INFO $path_info;
        fastcgi_pass unix:/var/run/php/php8.3-fpm.sock;
        fastcgi_intercept_errors on;
    }

    location ~* \.(?:css|js|woff2?|svg|gif|png|jpg|ico)$ {
        try_files $uri /index.php$request_uri;
        expires 6M;
        access_log off;
        add_header Cache-Control "public, immutable";
    }
}
```

#### Активация конфигурации
Создайте символическую ссылку для включения сайта, удалите дефолтный шаблон Nginx и перезапустите службу:
```bash
sudo ln -s /etc/nginx/sites-available/nextcloud /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

---

### Шаг 8. Завершение установки через веб-интерфейс

1. Откройте веб-браузер и перейдите по адресу: `https://192.168.24.11`.
     * *Пользователь БД*: `nextclouduser`
     * *Пароль БД*: `StrongPassword123!`

---

### Шаг 9. Финальные штрихи (Пост-настройка)

#### Проверка доверенных доменов (trusted_domains)
Вручную проверьте, зафиксирован ли ваш IP-адрес в конфигурационном файле приложения:
```bash
sudo nano /var/www/nextcloud/config/config.php
```
Внутри массива должен присутствовать ваш адрес:
```php
'trusted_domains' => 
array (
  0 => '192.168.24.11',
),
```

#### Настройка планировщика Cron
Nextcloud требует регулярного выполнения фоновых задач оптимизации. Переведите их на системный крон пользователя веб-сервера:
```bash
sudo crontab -u www-data -e
```
Добавьте в самый конец файла следующую строку (выполнение каждые 5 минут):
```text
*/5 * * * * php -f /var/www/nextcloud/cron.php
```

#### Настройка встроенного файрвола (UFW)
Разрешите входящие соединения для веб-трафика и активируйте защиту межсетевого экрана:
```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
```

---

## Готово к эксплуатации!

     * *Имя БД*: `nextcloud`
     * *Хост*: `localhost`
4. Нажмите кнопку **«Завершить установку»** и дождитесь инициализации интерфейса.

