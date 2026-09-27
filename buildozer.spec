[app]
title = AutoDoctor Pro
package.name = autodoctor
package.domain = org.autodoctor
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt
version = 1.0.0
requirements = python3,kivy==2.1.0,pyjnius,reportlab,setuptools
orientation = portrait
fullscreen = 0
​android.permissions = INTERNET, ACCESS_NETWORK_STATE, BLUETOOTH, BLUETOOTH_ADMIN, BLUETOOTH_CONNECT, BLUETOOTH_SCAN, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
​[buildozer]
log_level = 2
warn_on_root = 1
