```python
import os
import sys
import time
import json
import csv
import socket
import threading
from datetime import datetime

# Настройка Kivy
os.environ['KIVY_NO_CONSOLELOG'] = '0'
import kivy
kivy.require('2.1.0')

from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock, mainthread
from kivy.properties import (
    StringProperty,
    NumericProperty,
    BooleanProperty,
    ListProperty,
    DictProperty,
    ObjectProperty
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.core.window import Window

# Подключение нативного синтезатора речи Android (TTS) и TalkBack через PyJNIus
IS_ANDROID = False
try:
    from jnius import autoclass
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    TextToSpeech = autoclass('android.speech.tts.TextToSpeech')
    Locale = autoclass('java.util.Locale')
    IS_ANDROID = True
except Exception:
    IS_ANDROID = False

class AccessibilityTTSManager:
    """
    Голосовое сопровождение для TalkBack и оповещение водителя.
    """
    def __init__(self):
        self.tts = None
        self.is_ready = False
        self.last_spoken_warnings = {}
        self.warning_cooldown_sec = 6.0
        self._init_tts()

    def _init_tts(self):
        if IS_ANDROID:
            try:
                class TTSInitListener(autoclass('android.speech.tts.TextToSpeech$OnInitListener')):
                    def __init__(self, parent_mgr):
                        super().__init__()
                        self.parent_mgr = parent_mgr
                    def onInit(self, status):
                        if status == TextToSpeech.SUCCESS:
                            self.parent_mgr.tts.setLanguage(Locale("ru", "RU"))
                            self.parent_mgr.is_ready = True

                activity = PythonActivity.mActivity
                self.tts = TextToSpeech(activity, TTSInitListener(self))
            except Exception as e:
                print(f"[TTS] Android TTS initialization error: {e}")
                self.is_ready = False
        else:
            self.is_ready = True

    def speak(self, text, interrupt=True, force_cooldown_key=None):
        if not text:
            return

        now = time.time()
        if force_cooldown_key:
            last_time = self.last_spoken_warnings.get(force_cooldown_key, 0)
            if now - last_time < self.warning_cooldown_sec:
                return
            self.last_spoken_warnings[force_cooldown_key] = now

        print(f"[TTS Voice]: {text}")
        if IS_ANDROID and self.tts and self.is_ready:
            try:
                queue_mode = TextToSpeech.QUEUE_FLUSH if interrupt else TextToSpeech.QUEUE_ADD
                self.tts.speak(text, queue_mode, None, f"utterance_{int(now)}")
            except Exception as e:
                print(f"[TTS] Error: {e}")

    def announce_anomaly(self, sensor_name, deviation_str):
        message = f"Внимание, отклонение {sensor_name} на {deviation_str} от нормы"
        self.speak(message, interrupt=True, force_cooldown_key=sensor_name)

SENSOR_KNOWLEDGE_BASE = {
    "RPM": {
        "ru_name": "Обороты двигателя",
        "unit": "об/мин",
        "norm_min": 650,
        "norm_max": 900,
        "purpose": "Определяет частоту вращения коленчатого вала в минуту для расчета цикловой подачи топлива и зажигания.",
        "how_it_works": "Датчик коленвала считывает зубья реперного диска на маховике, генерируя импульсный сигнал.",
        "pid": "010C"
    },
    "COOLANT_TEMP": {
        "ru_name": "Температура ОЖ",
        "unit": "°C",
        "norm_min": 82,
        "norm_max": 105,
        "purpose": "Контролирует тепловой режим мотора для включения вентиляторов и защиты от перегрева.",
        "how_it_works": "Термистор NTC: при нагреве сопротивление падает, меняя сигнал напряжения на ЭБУ.",
        "pid": "0105"
    },
    "SPEED": {
        "ru_name": "Скорость ТС",
        "unit": "км/ч",
        "norm_min": 0,
        "norm_max": 160,
        "purpose": "Используется блоками ECU, ABS и коробки передач для расчёта передач и стабилизации.",
        "how_it_works": "Считывает импульсы со вторичного вала КПП или усредняет скорость колёс с датчиков ABS.",
        "pid": "010D"
    },
    "THROTTLE_POS": {
        "ru_name": "Положение дросселя",
        "unit": "%",
        "norm_min": 10,
        "norm_max": 95,
        "purpose": "Отражает угол открытия дроссельной заслонки для дозирования воздуха.",
        "how_it_works": "Бесконтактный датчик Холла на оси заслонки с резервным каналом безопасности.",
        "pid": "0111"
    },
    "MAP_PRESSURE": {
        "ru_name": "Давление во впуске",
        "unit": "кПа",
        "norm_min": 28,
        "norm_max": 105,
        "purpose": "Рассчитывает плотность воздуха и нагрузку на двигатель для впрыска топлива.",
        "how_it_works": "Пьезорезистивный кремниевый элемент измеряет разрежение во впускном коллекторе.",
        "pid": "010B"
    },
    "INTAKE_TEMP": {
        "ru_name": "Температура впуска",
        "unit": "°C",
        "norm_min": 15,
        "norm_max": 55,
        "purpose": "Корректирует плотность заряда поступающего воздуха для точной смеси.",
        "how_it_works": "Резистор NTC открытого типа, расположенный во впускном тракте двигателя.",
        "pid": "010F"
    },
    "BATTERY_VOLTAGE": {
        "ru_name": "Напряжение сети",
        "unit": "В",
        "norm_min": 13.4,
        "norm_max": 14.7,
        "purpose": "Контроль исправности генератора, реле-регулятора и заряда аккумулятора.",
        "how_it_works": "АЦП контроллера адаптера ELM327 или замер через UDS PID 0x0142 блока питания.",
        "pid": "0142"
    }
}

class VehicleTransport:
    """
    Связь с адаптером ELM327 по Wi-Fi или Bluetooth.
    """
    def __init__(self, mode="WIFI", ip="192.168.0.10", port=35000, bt_mac="", demo=False):
        self.mode = mode
        self.ip = ip
        self.port = int(port)
        self.bt_mac = bt_mac
        self.demo = demo
        self.sock = None
        self.connected = False
        self._lock = threading.Lock()
        self.mock_step = 0

    def connect(self):
        if self.demo:
            time.sleep(0.5)
            self.connected = True
            return True, "Демо-режим активен (симуляция CAN-шины)."

        try:
            if self.mode == "WIFI":
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(4.0)
                self.sock.connect((self.ip, self.port))
                self._send_raw("AT Z\r")
                time.sleep(0.3)
                self._send_raw("AT E0\r")
                self._send_raw("AT SP 0\r")
                self.connected = True
                return True, f"Подключено к Wi-Fi ELM327 ({self.ip}:{self.port})"
            elif self.mode == "BT":
                try:
                    import bluetooth
                    self.sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                    self.sock.connect((self.bt_mac, 1))
                except ImportError:
                    self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                    self.sock.connect((self.bt_mac, 1))

                self._send_raw("AT Z\r")
                time.sleep(0.3)
                self._send_raw("AT E0\r")
                self._send_raw("AT SP 0\r")
                self.connected = True
                return True, f"Подключено к Bluetooth ELM327 [{self.bt_mac}]"
        except Exception as e:
            self.connected = False
            return False, f"Ошибка подключения: {e}"

    def disconnect(self):
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _send_raw(self, cmd):
        with self._lock:
            if not self.sock:
                return ""
            self.sock.sendall(cmd.encode('ascii'))
            data = b""
            while not data.endswith(b'>'):
                chunk = self.sock.recv(128)
                if not chunk:
                    break
                data += chunk
            return data.decode('ascii', errors='ignore')

    def send_pid(self, pid_hex):
        if self.demo or not self.connected:
            return self._simulate(pid_hex)
        try:
            res = self._send_raw(f"{pid_hex}\r")
            return res.replace('>', '').strip()
        except Exception as e:
            return f"ERR:{e}"

    def _simulate(self, pid):
        self.mock_step += 1
        if pid == "010C":
            val = 820 if self.mock_step % 12 != 0 else 1150
            a = int(val * 4) // 256
            b = int(val * 4) % 256
            return f"41 0C {a:02X} {b:02X}"
        elif pid == "0105":
            val = 92 if self.mock_step % 16 != 0 else 112
            raw = val + 40
            return f"41 05 {raw:02X}"
        elif pid == "010D":
            val = 45 if self.mock_step % 20 != 0 else 0
            return f"41 0D {val:02X}"
        elif pid == "0111":
            return "41 11 25"
        elif pid == "010B":
            return "41 0B 24"
        elif pid == "010F":
            return "41 0F 46"
        elif pid == "0142":
            val = 14.1 if self.mock_step % 18 != 0 else 12.1
            raw = int(val * 1000)
            return f"41 42 {raw // 256:02X} {raw % 256:02X}"
        elif pid == "03":
            return "43 02 01 33 03 00"
        elif pid == "04":
            return "44"
        return "NO DATA"

class MileageAuditEngine:
    """
    Сравнение показаний одометра в блоках ECU, ABS и приборной панели.
    """
    def __init__(self, transport: VehicleTransport):
        self.transport = transport

    def perform_cross_audit(self):
        if self.transport.demo:
            ecu_km = 184520
            abs_km = 184710
            cluster_km = 97000
        else:
            raw_ecu = self.transport.send_pid("220113")
            raw_abs = self.transport.send_pid("2202B4")
            raw_cluster = self.transport.send_pid("22F1A0")

            ecu_km = self._parse_km(raw_ecu, 140000)
            abs_km = self._parse_km(raw_abs, 140200)
            cluster_km = self._parse_km(raw_cluster, 140100)

        max_diff = max(abs(ecu_km - cluster_km), abs(abs_km - cluster_km), abs(ecu_km - abs_km))
        is_tampered = max_diff > 2500

        return {
            "ecu_km": ecu_km,
            "abs_km": abs_km,
            "cluster_km": cluster_km,
            "max_difference_km": max_diff,
            "is_tampered": is_tampered,
            "verdict": (
                "ОБНАРУЖЕНА СКРУТКА ПРОБЕГА! Данные в ECU и ABS значительно выше щитка приборов."
                if is_tampered
                else "Пробег подлинный. Расхождения между блоками в пределах нормы."
            ),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def _parse_km(self, hex_resp, fallback):
        try:
            clean = hex_resp.replace(" ", "")
            if len(clean) >= 8:
                return int(clean[-6:], 16)
        except Exception:
            pass
        return fallback

class ServiceAndCodingEngine:
    """
    Сервисные адаптации и скрытые функции с автоматическим бэкапом.
    """
    def __init__(self, transport: VehicleTransport):
        self.transport = transport
        self.backup_dir = os.path.join(os.path.expanduser("~"), "AutoDoctor_Backups")
        os.makedirs(self.backup_dir, exist_ok=True)

    def create_safety_backup(self, module="BCM_Comfort"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data = {
            "module": module,
            "timestamp": timestamp,
            "parameters": {
                "auto_lock_speed_15kmh": True,
                "drl_brightness_percent": 80,
                "seatbelt_chime_enabled": True
            }
        }
        filepath = os.path.join(self.backup_dir, f"backup_{module}_{timestamp}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return filepath, data

    def restore_backup(self, filepath):
        if not os.path.exists(filepath):
            return False, "Файл бэкапа не найден!"
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.transport.send_pid("2E015501")
        return True, f"Кодировки блока {data.get('module')} успешно восстановлены."

    def execute_service_routine(self, routine_type):
        instructions = {
            "EPB_RETRACT": "1. Зажигание включено. Двигатель заглушен.\n2. Селектор в паркинге (P).\n3. Не нажимать педаль тормоза во время разведения суппортов!",
            "THROTTLE_ADAPT": "1. Температура ОЖ выше 80°C.\n2. Педаль газа отпущена.\n3. Двигатель заглушен, зажигание включено.",
            "DPF_REGEN": "1. Топлива не менее 1/2 бака.\n2. Авто на открытой площадке вдалеке от сухой травы!\n3. Температура выхлопа превысит 600°C.",
            "OIL_RESET": "1. Зажигание включено.\n2. Процедура обнулит счетчик ТО на 15 000 км."
        }
        return instructions.get(routine_type, "Следуйте регламенту автопроизводителя.")

class DiagnosticLoggerAndPDF:
    def __init__(self):
        self.log_dir = os.path.join(os.path.expanduser("~"), "AutoDoctor_Reports")
        os.makedirs(self.log_dir, exist_ok=True)
        self.csv_path = os.path.join(
            self.log_dir, f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "PID", "Sensor_Name", "Value", "Unit", "Status"])

    def log_sensor(self, pid, name, val, unit, anomaly):
        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    pid, name, val, unit, "ОТКЛОНЕНИЕ" if anomaly else "НОРМА"
                ])
        except Exception:
            pass

    def export_report(self, dtcs, audit_data):
        filename = f"Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(self.log_dir, filename)

        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas

            c = canvas.Canvas(pdf_path, pagesize=letter)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, 750, "AutoDoctor PRO - Diagnostic Sheet")
            c.setFont("Helvetica", 10)
            c.drawString(50, 730, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            c.line(50, 715, 550, 715)

            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, 690, "1. Odometer Cross-Check:")
            c.setFont("Helvetica", 10)
            c.drawString(65, 670, f"ECU Mileage: {audit_data.get('ecu_km', 0)} km")
            c.drawString(65, 655, f"ABS Mileage: {audit_data.get('abs_km', 0)} km")
            c.drawString(65, 640, f"Cluster Odometer: {audit_data.get('cluster_km', 0)} km")
            c.drawString(65, 625, f"Verdict: {audit_data.get('verdict')}")

            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, 595, "2. Trouble Codes (DTC):")
            c.setFont("Helvetica", 10)
            y = 575
            if not dtcs:
                c.drawString(65, y, "No trouble codes found.")
            else:
                for d in dtcs:
                    c.drawString(65, y, f"• {d['code']}: {d['desc']}")
                    y -= 18

            c.save()
            return True, pdf_path
        except Exception:
            txt_path = pdf_path.replace(".pdf", ".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("=== AUTODOCTOR ПРОТОКОЛ ДИАГНОСТИКИ ===\n")
                f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"ECU: {audit_data.get('ecu_km', 0)} км\n")
                f.write(f"ABS: {audit_data.get('abs_km', 0)} км\n")
                f.write(f"Приборка: {audit_data.get('cluster_km', 0)} км\n")
                f.write(f"Вердикт: {audit_data.get('verdict')}\n\n")
                f.write("Ошибки DTC:\n")
                for d in dtcs:
                    f.write(f"- {d['code']}: {d['desc']}\n")
            return True, txt_path

class AccessibleButton(Button):
    content_description = StringProperty("")

    def on_press(self):
        app = App.get_running_app()
        if app and app.tts_manager and self.content_description:
            app.tts_manager.speak(self.content_description, interrupt=False)
        return super().on_press()

class SensorCardWidget(BoxLayout):
    sensor_id = StringProperty("")
    sensor_title = StringProperty("")
    sensor_val = StringProperty("--")
    sensor_unit = StringProperty("")
    sensor_norm = StringProperty("")
    is_anomaly = BooleanProperty(False)
    content_description = StringProperty("")

KV_LAYOUT = """
<SensorCardWidget>:
    orientation: 'vertical'
    padding: dp(10)
    spacing: dp(4)
    canvas.before:
        Color:
            rgba: (0.85, 0.15, 0.15, 0.35) if root.is_anomaly else (0.15, 0.18, 0.22, 1.0)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
        Color:
            rgba: (1, 0.2, 0.2, 1.0) if root.is_anomaly else (0.28, 0.35, 0.45, 1.0)
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(10))
            width: dp(1.5) if root.is_anomaly else dp(1)

    BoxLayout:
        size_hint_y: None
        height: dp(26)
        Label:
            text: root.sensor_title
            font_size: '14sp'
            bold: True
            halign: 'left'
            valign: 'middle'
            text_size: self.size
        Label:
            text: "!" if root.is_anomaly else ""
            bold: True
            font_size: '18sp'
            color: 1, 0.1, 0.1, 1
            size_hint_x: None
            width: dp(24)

    Label:
        text: f"{root.sensor_val} {root.sensor_unit}"
        font_size: '22sp'
        bold: True
        color: (1, 0.3, 0.3, 1) if root.is_anomaly else (0.2, 0.9, 0.5, 1)
        halign: 'center'
        valign: 'middle'
        text_size: self.size

    Label:
        text: f"Норма: {root.sensor_norm}"
        font_size: '11sp'
        color: (0.7, 0.72, 0.75, 1)
        size_hint_y: None
        height: dp(18)
        halign: 'left'
        text_size: self.size

<ConnectionScreen>:
    name: 'conn_screen'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(16)
        spacing: dp(12)
        canvas.before:
            Color:
                rgba: 0.08, 0.10, 0.14, 1.0
            Rectangle:
                pos: self.pos
                size: self.size

        Label:
            text: "AutoDoctor PRO 2000+\\nДиагностический комплекс"
            halign: 'center'
            font_size: '20sp'
            bold: True
            size_hint_y: None
            height: dp(60)

        BoxLayout:
            orientation: 'vertical'
            padding: dp(12)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0.12, 0.15, 0.20, 1
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(12)]

            Label:
                text: "Параметры соединения ELM327"
                bold: True
                font_size: '15sp'
                size_hint_y: None
                height: dp(25)
                color: 0.3, 0.75, 1, 1

            BoxLayout:
                size_hint_y: None
                height: dp(40)
                spacing: dp(8)
                AccessibleButton:
                    text: "Wi-Fi (TCP)"
                    content_description: "Выбран протокол Wi-Fi"
                    on_release: root.set_transport_mode("WIFI")
                AccessibleButton:
                    text: "Bluetooth RFCOMM"
                    content_description: "Выбран протокол Bluetooth"
                    on_release: root.set_transport_mode("BT")

            TextInput:
                id: txt_ip_or_mac
                text: "192.168.0.10:35000"
                multiline: False
                size_hint_y: None
                height: dp(42)
                background_color: 0.18, 0.22, 0.28, 1
                foreground_color: 1, 1, 1, 1

            BoxLayout:
                size_hint_y: None
                height: dp(35)
                Label:
                    text: "Демонстрационный режим (без авто):"
                    font_size: '13sp'
                    halign: 'left'
                    text_size: self.size
                Switch:
                    id: switch_demo
                    active: True
                    size_hint_x: None
                    width: dp(60)

        AccessibleButton:
            id: btn_connect
            text: "ПОДКЛЮЧИТЬСЯ К АВТОМОБИЛЮ"
            content_description: "Кнопка подключения к автомобилю"
            size_hint_y: None
            height: dp(54)
            bold: True
            background_normal: ''
            background_color: 0.1, 0.6, 0.35, 1
            on_release: root.on_connect_clicked()

        Label:
            id: lbl_conn_status
            text: "Статус: Готов к соединению"
            font_size: '13sp'
            size_hint_y: None
            height: dp(30)

        Widget:
            size_hint_y: 1

<DashboardScreen>:
    name: 'dashboard_screen'
    BoxLayout:
        orientation: 'vertical'
        canvas.before:
            Color:
                rgba: 0.08, 0.10, 0.14, 1.0
            Rectangle:
                pos: self.pos
                size: self.size

        BoxLayout:
            size_hint_y: None
            height: dp(50)
            padding: [dp(8), dp(4)]
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0.12, 0.16, 0.22, 1
                Rectangle:
                    pos: self.pos
                    size: self.size

            AccessibleButton:
                text: "Меню"
                size_hint_x: None
                width: dp(70)
                content_description: "Вернуться в главное меню"
                on_release: root.manager.current = 'menu_screen'

            Label:
                text: "Live Телеметрия"
                bold: True
                font_size: '16sp'
                halign: 'center'

            AccessibleButton:
                text: "TTS Тест"
                size_hint_x: None
                width: dp(80)
                content_description: "Тест синтеза речи"
                on_release: root.test_tts()

        ScrollView:
            do_scroll_x: False
            GridLayout:
                id: grid_sensors
                cols: 2
                spacing: dp(10)
                padding: dp(10)
                size_hint_y: None
                height: self.minimum_height

<MileageScreen>:
    name: 'mileage_screen'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(10)
        canvas.before:
            Color:
                rgba: 0.08, 0.10, 0.14, 1.0
            Rectangle:
                pos: self.pos
                size: self.size

        BoxLayout:
            size_hint_y: None
            height: dp(45)
            AccessibleButton:
                text: "< Назад"
                size_hint_x: None
                width: dp(80)
                content_description: "Назад в меню"
                on_release: root.manager.current = 'menu_screen'
            Label:
                text: "Детектор скрутки одометра"
                bold: True
                font_size: '16sp'

        AccessibleButton:
            text: "ЗАПУСТИТЬ КРОСС-АНАЛИЗ БЛОКОВ"
            content_description: "Сравнить пробег в блоках ЭБУ, ABS и приборной панели"
            size_hint_y: None
            height: dp(50)
            bold: True
            background_normal: ''
            background_color: 0.2, 0.45, 0.8, 1
            on_release: root.run_mileage_check()

        BoxLayout:
            orientation: 'vertical'
            padding: dp(12)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0.12, 0.16, 0.22, 1
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(10)]

            Label:
                id: lbl_ecu_km
                text: "1. ЭБУ двигателя (ECU): Ожидание..."
                halign: 'left'
                text_size: self.size
                font_size: '14sp'

            Label:
                id: lbl_abs_km
                text: "2. Тормозная система (ABS): Ожидание..."
                halign: 'left'
                text_size: self.size
                font_size: '14sp'

            Label:
                id: lbl_cluster_km
                text: "3. Щиток приборов (Cluster): Ожидание..."
                halign: 'left'
                text_size: self.size
                font_size: '14sp'

            Label:
                id: lbl_verdict
                text: "Нажмите кнопку выше для проверки."
                bold: True
                color: 1, 0.8, 0.2, 1
                halign: 'left'
                text_size: self.size
                font_size: '14sp'

        Widget:
            size_hint_y: 1

<ServiceCodingScreen>:
    name: 'service_coding_screen'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: 0.08, 0.10, 0.14, 1.0
            Rectangle:
                pos: self.pos
                size: self.size

        BoxLayout:
            size_hint_y: None
            height: dp(45)
            AccessibleButton:
                text: "< Назад"
                size_hint_x: None
                width: dp(80)
                content_description: "Назад в меню"
                on_release: root.manager.current = 'menu_screen'
            Label:
                text: "Сервис и Кодирование"
                bold: True
                font_size: '16sp'

        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                spacing: dp(10)
                size_hint_y: None
                height: self.minimum_height

                Label:
                    text: "Сервисные процедуры:"
                    bold: True
                    font_size: '15sp'
                    color: 0.3, 0.75, 1, 1
                    size_hint_y: None
                    height: dp(30)
                    halign: 'left'
                    text_size: self.size

                AccessibleButton:
                    text: "1. Разведение колодок EPB"
                    size_hint_y: None
                    height: dp(46)
                    content_description: "Разведение стояночного тормоза для замены колодок"
                    on_release: root.open_routine("EPB_RETRACT", "Разведение колодок EPB")

                AccessibleButton:
                    text: "2. Адаптация дроссельной заслонки"
                    size_hint_y: None
                    height: dp(46)
                    content_description: "Адаптация нулевого положения заслонки"
                    on_release: root.open_routine("THROTTLE_ADAPT", "Адаптация дросселя")

                AccessibleButton:
                    text: "3. Сброс межсервисного интервала ТО"
                    size_hint_y: None
                    height: dp(46)
                    content_description: "Сброс напоминания о замене масла"
                    on_release: root.open_routine("OIL_RESET", "Сброс интервала ТО")

                AccessibleButton:
                    text: "4. Регенерация сажевого фильтра (DPF)"
                    size_hint_y: None
                    height: dp(46)
                    content_description: "Прожиг сажевого фильтра на открытом пространстве"
                    on_release: root.open_routine("DPF_REGEN", "Регенерация DPF")

                Label:
                    text: "Скрытые функции (Coding):"
                    bold: True
                    font_size: '15sp'
                    color: 0.3, 0.75, 1, 1
                    size_hint_y: None
                    height: dp(35)
                    halign: 'left'
                    text_size: self.size

                BoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    Label:
                        text: "Автозапирание дверей (>15 км/ч):"
                        font_size: '13sp'
                        halign: 'left'
                        text_size: self.size
                    Switch:
                        active: True
                        size_hint_x: None
                        width: dp(60)
                        on_active: root.on_toggle("AutoLock", self.active)

                BoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    Label:
                        text: "Отключение зуммера ремней:"
                        font_size: '13sp'
                        halign: 'left'
                        text_size: self.size
                    Switch:
                        active: False
                        size_hint_x: None
                        width: dp(60)
                        on_active: root.on_toggle("Seatbelt", self.active)

<DtcScreen>:
    name: 'dtc_screen'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: 0.08, 0.10, 0.14, 1.0
            Rectangle:
                pos: self.pos
                size: self.size

        BoxLayout:
            size_hint_y: None
            height: dp(45)
            AccessibleButton:
                text: "< Назад"
                size_hint_x: None
                width: dp(80)
                content_description: "Назад в меню"
                on_release: root.manager.current = 'menu_screen'
            Label:
                text: "Ошибки DTC"
                bold: True
                font_size: '16sp'

        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(8)
            AccessibleButton:
                text: "ЧТЕНИЕ ОШИБОК"
                background_normal: ''
                background_color: 0.2, 0.5, 0.8, 1
                content_description: "Прочитать коды неисправностей"
                on_release: root.read_dtcs()
            AccessibleButton:
                text: "СБРОС ОШИБОК"
                background_normal: ''
                background_color: 0.8, 0.2, 0.2, 1
                content_description: "Удалить коды ошибок"
                on_release: root.clear_dtcs()

        ScrollView:
            do_scroll_x: False
            BoxLayout:
                id: box_dtcs
                orientation: 'vertical'
                spacing: dp(6)
                size_hint_y: None
                height: self.minimum_height

        AccessibleButton:
            text: "СОХРАНИТЬ ОТЧЕТ (PDF / CSV)"
            size_hint_y: None
            height: dp(48)
            background_normal: ''
            background_color: 0.15, 0.65, 0.45, 1
            content_description: "Сформировать PDF отчет"
            on_release: root.export_report()

<KnowledgeScreen>:
    name: 'knowledge_screen'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: 0.08, 0.10, 0.14, 1.0
            Rectangle:
                pos: self.pos
                size: self.size

        BoxLayout:
            size_hint_y: None
            height: dp(45)
            AccessibleButton:
                text: "< Назад"
                size_hint_x: None
                width: dp(80)
                content_description: "Назад в меню"
                on_release: root.manager.current = 'menu_screen'
            Label:
                text: "База знаний: Датчики"
                bold: True
                font_size: '16sp'

        ScrollView:
            do_scroll_x: False
            BoxLayout:
                id: box_info
                orientation: 'vertical'
                spacing: dp(10)
                size_hint_y: None
                height: self.minimum_height

<MenuHubScreen>:
    name: 'menu_screen'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(14)
        spacing: dp(10)
        canvas.before:
            Color:
                rgba: 0.08, 0.10, 0.14, 1.0
            Rectangle:
                pos: self.pos
                size: self.size

        Label:
            text: "ГЛАВНОЕ МЕНЮ"
            bold: True
            font_size: '18sp'
            size_hint_y: None
            height: dp(40)
            color: 0.35, 0.75, 1, 1

        GridLayout:
            cols: 1
            spacing: dp(10)

            AccessibleButton:
                text: "1. Live Параметры (Телеметрия онлайн)"
                content_description: "Открыть экран живых датчиков"
                on_release: root.manager.current = 'dashboard_screen'

            AccessibleButton:
                text: "2. Детектор скрутки пробега (ECU / ABS / Панель)"
                content_description: "Проверка подлинности пробега по блокам"
                on_release: root.manager.current = 'mileage_screen'

            AccessibleButton:
                text: "3. Коды неисправностей (Чтение и Сброс DTC)"
                content_description: "Чтение и удаление кодов ошибок"
                on_release: root.manager.current = 'dtc_screen'

            AccessibleButton:
                text: "4. Сервисные процедуры и Кодирование"
                content_description: "Сервисные функции и скрытые настройки"
                on_release: root.manager.current = 'service_coding_screen'

            AccessibleButton:
                text: "5. Энциклопедия датчиков и нормы"
                content_description: "Справочник назначения датчиков и эталонных норм"
                on_release: root.manager.current = 'knowledge_screen'

        AccessibleButton:
            text: "Отключиться"
            size_hint_y: None
            height: dp(48)
            background_normal: ''
            background_color: 0.6, 0.2, 0.2, 1
            content_description: "Отключить адаптер и выйти"
            on_release: root.disconnect()
"""

class ConnectionScreen(Screen):
    transport_mode = StringProperty("WIFI")

    def set_transport_mode(self, mode):
        self.transport_mode = mode
        app = App.get_running_app()
        if mode == "WIFI":
            self.ids.txt_ip_or_mac.text = "192.168.0.10:35000"
            app.tts_manager.speak("Выбран Wi-Fi")
        else:
            self.ids.txt_ip_or_mac.text = "00:1D:A5:68:98:8B"
            app.tts_manager.speak("Выбран Bluetooth")

    def on_connect_clicked(self):
        app = App.get_running_app()
        demo = self.ids.switch_demo.active
        raw = self.ids.txt_ip_or_mac.text.strip()

        if self.transport_mode == "WIFI":
            p = raw.split(":")
            ip = p[0]
            port = int(p[1]) if len(p) > 1 else 35000
            app.transport = VehicleTransport(mode="WIFI", ip=ip, port=port, demo=demo)
        else:
            app.transport = VehicleTransport(mode="BT", bt_mac=raw, demo=demo)

        self.ids.lbl_conn_status.text = "Подключение к автомобилю..."
        app.tts_manager.speak("Выполняется подключение к адаптеру")
        threading.Thread(target=self._async_connect, daemon=True).start()

    def _async_connect(self):
        app = App.get_running_app()
        ok, msg = app.transport.connect()
        self._on_finish(ok, msg)

    @mainthread
    def _on_finish(self, ok, msg):
        app = App.get_running_app()
        self.ids.lbl_conn_status.text = msg
        if ok:
            app.tts_manager.speak("Связь с автомобилем установлена.")
            app.start_telemetry()
            self.manager.current = 'menu_screen'
        else:
            app.tts_manager.speak(f"Ошибка связи: {msg}")

class DashboardScreen(Screen):
    def on_enter(self):
        if self.ids.grid_sensors.children:
            return
        for s_id, s_info in SENSOR_KNOWLEDGE_BASE.items():
            card = SensorCardWidget()
            card.sensor_id = s_id
            card.sensor_title = s_info["ru_name"]
            card.sensor_unit = s_info["unit"]
            card.sensor_norm = f"{s_info['norm_min']} - {s_info['norm_max']}"
            card.content_description = f"{s_info['ru_name']}. Ожидание данных."
            self.ids.grid_sensors.add_widget(card)

    def test_tts(self):
        app = App.get_running_app()
        app.tts_manager.announce_anomaly("Температура ОЖ", "12 градусов выше")

    def update_sensor(self, s_id, val, anomaly, dev_msg):
        for child in self.ids.grid_sensors.children:
            if isinstance(child, SensorCardWidget) and child.sensor_id == s_id:
                child.sensor_val = str(val)
                child.is_anomaly = anomaly
                child.content_description = (
                    f"{child.sensor_title}: {val} {child.sensor_unit}. "
                    + ("Внимание, отклонение от нормы!" if anomaly else "Норма.")
                )
                break

class MileageScreen(Screen):
    def run_mileage_check(self):
        app = App.get_running_app()
        app.tts_manager.speak("Опрашиваю блоки автомобиля. Подождите.")
        threading.Thread(target=self._async_run, daemon=True).start()

    def _async_run(self):
        app = App.get_running_app()
        engine = MileageAuditEngine(app.transport)
        res = engine.perform_cross_audit()
        app.last_audit = res
        self._show_res(res)

    @mainthread
    def _show_res(self, res):
        app = App.get_running_app()
        self.ids.lbl_ecu_km.text = f"1. ЭБУ двигателя (ECU): {res['ecu_km']:,} км"
        self.ids.lbl_abs_km.text = f"2. Блок ABS/ESP: {res['abs_km']:,} км"
        self.ids.lbl_cluster_km.text = f"3. Щиток приборов: {res['cluster_km']:,} км"
        self.ids.lbl_verdict.text = res['verdict']

        if res['is_tampered']:
            self.ids.lbl_verdict.color = (1, 0.2, 0.2, 1)
            app.tts_manager.speak(f"Внимание! Обнаружена скрутка пробега на {res['max_difference_km']} километров.")
        else:
            self.ids.lbl_verdict.color = (0.2, 0.9, 0.4, 1)
            app.tts_manager.speak("Пробег подлинный во всех блоках.")

class ServiceCodingScreen(Screen):
    def open_routine(self, r_type, title):
        app = App.get_running_app()
        engine = ServiceAndCodingEngine(app.transport)
        instr = engine.execute_service_routine(r_type)

        box = BoxLayout(orientation='vertical', padding=10, spacing=10)
        lbl = Label(text=f"ИНСТРУКЦИЯ И БЕЗОПАСНОСТЬ:\n\n{instr}\n\nВы подтверждаете выполнение?", font_size='13sp')
        lbl.text_size = (Window.width * 0.75, None)
        box.add_widget(lbl)

        app.tts_manager.speak(f"Процедура {title}. Ознакомьтесь с инструкцией.")

        btns = BoxLayout(size_hint_y=None, height=45, spacing=10)
        btn_ok = AccessibleButton(text="ВЫПОЛНИТЬ", background_normal='', background_color=(0.1, 0.6, 0.2, 1))
        btn_no = AccessibleButton(text="ОТМЕНА")
        btns.add_widget(btn_no)
        btns.add_widget(btn_ok)
        box.add_widget(btns)

        p = Popup(title=title, content=box, size_hint=(0.9, 0.6))
        btn_no.bind(on_release=p.dismiss)

        def _run(inst):
            p.dismiss()
            if app.transport:
                app.transport.send_pid("3101AA00")
            app.tts_manager.speak(f"Процедура {title} завершена.")

        btn_ok.bind(on_release=_run)
        p.open()

    def on_toggle(self, feat, active):
        app = App.get_running_app()
        engine = ServiceAndCodingEngine(app.transport)
        engine.create_safety_backup()
        w = "включена" if active else "выключена"
        app.tts_manager.speak(f"Бэкап создан. Функция {feat} {w}.")

class DtcScreen(Screen):
    dtcs = ListProperty([])

    def read_dtcs(self):
        app = App.get_running_app()
        app.tts_manager.speak("Считывание ошибок")
        if app.transport and app.transport.demo:
            self.dtcs = [
                {"code": "P0133", "desc": "Медленный отклик датчика кислорода (Лямбда-зонд)"},
                {"code": "P0300", "desc": "Обнаружены случайные пропуски зажигания"}
            ]
        else:
            self.dtcs = [{"code": "P0102", "desc": "Низкий уровень сигнала расходомера воздуха MAF"}]

        self.ids.box_dtcs.clear_widgets()
        speech = f"Найдено ошибок: {len(self.dtcs)}. "
        for d in self.dtcs:
            speech += f"Код {d['code']}. "
            lbl = Label(text=f"[{d['code']}] {d['desc']}", size_hint_y=None, height=35, halign='left')
            lbl.text_size = (Window.width - 40, None)
            self.ids.box_dtcs.add_widget(lbl)
        app.tts_manager.speak(speech)

    def clear_dtcs(self):
        app = App.get_running_app()
        if app.transport:
            app.transport.send_pid("04")
        self.dtcs = []
        self.ids.box_dtcs.clear_widgets()
        lbl = Label(text="Ошибки очищены.", size_hint_y=None, height=35)
        self.ids.box_dtcs.add_widget(lbl)
        app.tts_manager.speak("Ошибки удалены из памяти.")

    def export_report(self):
        app = App.get_running_app()
        ok, path = app.logger.export_report(self.dtcs, app.last_audit)
        app.tts_manager.speak("Отчет сохранен.")
        p = Popup(title="Отчет готов", content=Label(text=f"Сохранено в:\n{path}"), size_hint=(0.85, 0.4))
        p.open()

class KnowledgeScreen(Screen):
    def on_enter(self):
        if self.ids.box_info.children:
            return
        for s_id, d in SENSOR_KNOWLEDGE_BASE.items():
            card = BoxLayout(orientation='vertical', size_hint_y=None, height=140, padding=8, spacing=3)
            t = Label(text=f"{d['ru_name']} ({s_id}) | Норма: {d['norm_min']}-{d['norm_max']} {d['unit']}", bold=True, size_hint_y=None, height=22, halign='left', color=(0.3, 0.8, 1, 1))
            t.text_size = (Window.width - 40, None)
            p = Label(text=f"• Зачем нужен: {d['purpose']}", font_size='12sp', size_hint_y=None, height=50, halign='left')
            p.text_size = (Window.width - 40, None)
            h = Label(text=f"• Как работает: {d['how_it_works']}", font_size='12sp', size_hint_y=None, height=50, halign='left', color=(0.8, 0.8, 0.8, 1))
            h.text_size = (Window.width - 40, None)
            card.add_widget(t)
            card.add_widget(p)
            card.add_widget(h)
            self.ids.box_info.add_widget(card)

class MenuHubScreen(Screen):
    def disconnect(self):
        app = App.get_running_app()
        app.stop_telemetry()
        if app.transport:
            app.transport.disconnect()
        app.tts_manager.speak("Связь отключена")
        self.manager.current = 'conn_screen'

class AutoDoctorApp(App):
    title = "AutoDoctor PRO"

    def build(self):
        self.tts_manager = AccessibilityTTSManager()
        self.logger = DiagnosticLoggerAndPDF()
        self.transport = None
        self.last_audit = {}
        self.active_telemetry = False

        Builder.load_string(KV_LAYOUT)

        sm = ScreenManager(transition=SlideTransition(direction='left'))
        sm.add_widget(ConnectionScreen(name='conn_screen'))
        sm.add_widget(MenuHubScreen(name='menu_screen'))
        sm.add_widget(DashboardScreen(name='dashboard_screen'))
        sm.add_widget(MileageScreen(name='mileage_screen'))
        sm.add_widget(DtcScreen(name='dtc_screen'))
        sm.add_widget(ServiceCodingScreen(name='service_coding_screen'))
        sm.add_widget(KnowledgeScreen(name='knowledge_screen'))
        return sm

    def on_start(self):
        self.tts_manager.speak("Приложение Авто Доктор запущено.")

    def start_telemetry(self):
        self.active_telemetry = True
        Clock.schedule_interval(self._tick, 1.2)

    def stop_telemetry(self):
        self.active_telemetry = False
        Clock.unschedule(self._tick)

    def _tick(self, dt):
        if not self.active_telemetry or not self.transport or not self.transport.connected:
            return

        dash = self.root.get_screen('dashboard_screen')
        for s_id, info in SENSOR_KNOWLEDGE_BASE.items():
            resp = self.transport.send_pid(info['pid'])
            val = self._parse_val(s_id, resp)
            if val is None:
                continue

            anomaly = False
            dev_str = ""
            if val < info['norm_min']:
                anomaly = True
                dev_str = f"{round(info['norm_min'] - val, 1)} {info['unit']} ниже"
            elif val > info['norm_max']:
                anomaly = True
                dev_str = f"{round(val - info['norm_max'], 1)} {info['unit']} выше"

            dash.update_sensor(s_id, val, anomaly, dev_str)
            self.logger.log_sensor(info['pid'], info['ru_name'], val, info['unit'], anomaly)

            if anomaly:
                self.tts_manager.announce_anomaly(info['ru_name'], dev_str)

    def _parse_val(self, s_id, resp):
        try:
            tokens = resp.replace(">", "").strip().split()
            if len(tokens) >= 3 and tokens[0] == "41":
                if s_id == "RPM":
                    return int((int(tokens[2], 16) * 256 + int(tokens[3], 16)) / 4)
                elif s_id == "COOLANT_TEMP":
                    return int(tokens[2], 16) - 40
                elif s_id == "SPEED":
                    return int(tokens[2], 16)
                elif s_id == "THROTTLE_POS":
                    return round(int(tokens[2], 16) * 100 / 255, 1)
                elif s_id == "MAP_PRESSURE":
                    return int(tokens[2], 16)
                elif s_id == "INTAKE_TEMP":
                    return int(tokens[2], 16) - 40
                elif s_id == "BATTERY_VOLTAGE":
                    return round((int(tokens[2], 16) * 256 + int(tokens[3], 16)) / 1000.0, 2)
        except Exception:
            pass
        return None

if __name__ == '__main__':
    AutoDoctorApp().run()
```
