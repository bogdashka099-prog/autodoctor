[app]
# Название и пакет приложения
title = AutoDoctor Pro
package.name = autodoctor
package.domain = org.autodoctor

# Исходный код
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt

# Версия приложения
version = 1.0.0

# Необходимые Python-пакеты и библиотеки
# PyJNIus необходим для нативного Android TTS и TalkBack
requirements = python3,kivy==2.1.0,pyjnius,reportlab,setuptools

# Ориентация экрана
orientation = portrait

# Системные разрешения Android
# Для связи по Wi-Fi, классическому Bluetooth (включая Android 12+) и сохранения отчетов
android.permissions = INTERNET, ACCESS_NETWORK_STATE, BLUETOOTH, BLUETOOTH_ADMIN, BLUETOOTH_CONNECT, BLUETOOTH_SCAN, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE

# Целевые версии Android SDK / NDK
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

# Полноэкранный режим
fullscreen = 0

[buildozer]
# Уровень логирования сборщика (2 = подробный вывод ошибок)
log_level = 2
warn_on_root = 1
