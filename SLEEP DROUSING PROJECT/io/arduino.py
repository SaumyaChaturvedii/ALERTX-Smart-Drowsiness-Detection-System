import serial
import serial.tools.list_ports
import threading
import time
import logging

class ArduinoManager:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.logger = logger
        self._ser = None
        self._port_name = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._last_sig = ''
        self._last_time = 0.0
        self.INTERVAL = 0.1
        
        if self.cfg.USE_ARDUINO:
            self._connect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
            self._connect_thread.start()

    def _find_port(self):
        ports = serial.tools.list_ports.comports()
        for p in ports:
            if any(k in (p.description or '').lower() for k in ['arduino', 'ch340', 'usb serial', 'usb-serial']):
                return p.device
        return None

    def _reconnect_loop(self):
        while not self._stop_event.is_set():
            with self._lock:
                connected = self._ser is not None and self._ser.is_open
                
            if not connected:
                port = self._find_port() or self.cfg.SERIAL_PORT
                try:
                    ser = serial.Serial(port, self.cfg.BAUD_RATE, timeout=0.2, write_timeout=0.2)
                    with self._lock:
                        if self._stop_event.is_set():
                            ser.close()
                            break
                        self._ser = ser
                        self._port_name = port
                    self.logger.info(f"Arduino connected on {port}")
                except Exception as exc:
                    pass
            time.sleep(5)

    def send(self, signal: str):
        now = time.time()
        if signal == self._last_sig and now - self._last_time < self.INTERVAL:
            return
            
        with self._lock:
            if self._ser and self._ser.is_open:
                try:
                    # Append newline to signify command end for Arduino readStringUntil
                    self._ser.write((signal + '\n').encode())
                    self._last_sig = signal
                    self._last_time = now
                except Exception:
                    self._ser.close()
                    self._ser = None
                    self._port_name = None

    def close(self):
        self._stop_event.set()
        with self._lock:
            if self._ser:
                try:
                    self._ser.write(b'N\n')
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
        
    @property
    def connected(self):
        with self._lock:
            return bool(self._ser and self._ser.is_open)
