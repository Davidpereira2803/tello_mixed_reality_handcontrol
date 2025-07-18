#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray, Empty
import socket
import threading
import time

ESP32_IP = "192.168.4.2"
ESP32_PORT = 8888

TAKEOFF_THRESHOLD = 0.9
LAND_THRESHOLD = -0.9
TAKEOFFLAND_HOLD_TIME = 1

class ESP32Publisher(Node):
    def __init__(self):
        super().__init__('esp32_publisher')
        
        self.publisher_ = self.create_publisher(Float32MultiArray, '/esp32/inclinometer', 10)

        self.create_subscription(Empty, '/calibrate', self.trigger_calibration, 10)
        
        self.sock = None
        self.get_logger().info("Starting ESP32 UDP listener...")

        while self.sock is None and rclpy.ok():
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.bind((ESP32_IP, ESP32_PORT))

                self.get_logger().info("ESP32 UDP listener started. Waiting for data...")
            except Exception as e:
                self.get_logger().error(f"Error starting ESP32 UDP listener: {e}")
                self.sock = None
                time.sleep(3)

        if self.sock:
            self.takeoff_triggered = False
            self.land_triggered = False
            self.takeoff_start_time = None
            self.land_start_time = None
            self.receive_data_active = True
            self.calibration_values = {'roll': 0.0, 'pitch': 0.0}

            self.receive_thread = threading.Thread(target=self.receive_data, daemon=True)
            self.receive_thread.start()

    def receive_data(self):
        """Continuously receive UDP packets from ESP32 and publish to ROS2."""
        while rclpy.ok():
            if not self.receive_data_active:
                time.sleep(0.1)
                continue
            try:
                data, addr = self.sock.recvfrom(1024)
                decoded_data = data.decode().strip()
                self.get_logger().info(f"Received: {decoded_data}")

                parts = decoded_data.split(",")
                ax = float(parts[0].split(":")[1])
                ay = float(parts[1].split(":")[1])
                az = float(parts[2].split(":")[1])
                gx = float(parts[3].split(":")[1])
                gy = float(parts[4].split(":")[1])
                gz = float(parts[5].split(":")[1])


                roll = ax - self.calibration_values['roll']
                pitch = ay - self.calibration_values['pitch']
                up_down_movement = az
                yaw = gz

                self.take_off(pitch)    
                self.land(pitch)

                msg = Float32MultiArray()
                msg.data = [roll, pitch, self.takeoff_triggered, self.land_triggered, up_down_movement, yaw]

                self.publisher_.publish(msg)

            except Exception as e:
                self.get_logger().error(f"Error receiving ESP32 data: {e}")
    
    def take_off(self, pitch):
        """Publish takeoff message."""
        if not self.takeoff_triggered:
            if pitch > TAKEOFF_THRESHOLD:
                if self.takeoff_start_time is None:
                    self.takeoff_start_time = time.time()
                elif time.time() - self.takeoff_start_time > TAKEOFFLAND_HOLD_TIME:
                    self.takeoff_triggered = True
                    self.land_triggered = False
            else:
                self.takeoff_start_time = None
            
    def land(self, pitch):
        """Publish land message."""
        if not self.land_triggered and self.takeoff_triggered:
            if pitch < LAND_THRESHOLD:
                if self.land_start_time is None:
                    self.land_start_time = time.time()
                elif time.time() - self.land_start_time > TAKEOFFLAND_HOLD_TIME:
                    self.land_triggered = True
                    self.takeoff_triggered = False
            else:
                self.land_start_time = None

    def trigger_calibration(self, msg):
        """Trigger calibration process."""
        self.get_logger().info("Triggering calibration...")
        self.receive_data_active = False
        time.sleep(0.5)

        self.calibration()
        self.receive_data_active = True

    def _wait_for_data(self):
        """Wait for data from ESP32."""
        while True:
            try:
                data, _ = self.sock.recvfrom(1024)
                decoded_data = data.decode().strip()
                parts = decoded_data.split(",")
                ax = float(parts[0].split(":")[1])
                ay = float(parts[1].split(":")[1])
                return {'roll': ax, 'pitch': ay}
            except:
                continue

    def calibration(self):
        self.get_logger().info("Calibrating ESP32 sensor...")

        self.get_logger().info(" Place the inclinometer in neutral PITCH position.")
        time.sleep(5)
        data = self._wait_for_data()
        self.calibration_values['pitch'] = data['pitch']
        self.get_logger().info(f"Pitch calibrated to {data['pitch']:.2f}")

        self.get_logger().info("Place the inclinometer in neutral ROLL position.")
        time.sleep(5)
        data = self._wait_for_data()
        self.calibration_values['roll'] = data['roll']
        self.get_logger().info(f"Roll calibrated to {data['roll']:.2f}")

        self.get_logger().info("Calibration complete.")
