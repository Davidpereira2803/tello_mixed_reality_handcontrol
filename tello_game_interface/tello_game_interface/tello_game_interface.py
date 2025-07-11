import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Image
import cv2
import cv2.aruco as aruco
from cv_bridge import CvBridge
import numpy as np
import pygame
from tello_msgs.msg import PS4Buttons, Game, GameStatus, ModeStatus
import threading

from vosk import Model, KaldiRecognizer
import sounddevice as sd
import queue
import json
from datetime import datetime
import csv

class TelloGame(Node):
    def __init__(self):
        super().__init__('tello_game_node')

        self.bridge = CvBridge()
        self.subscription = self.create_subscription(Image, '/camera/image_raw', self.image_callback, 10)
        self.ps4_btn_sub = self.create_subscription(PS4Buttons, '/ps4_btn', self.ps4_button_callback, 10)
        self.trigger_state_sub = self.create_subscription(Game, '/trigger_state', self.update_trigger_state, 10)
        self.control_mode_status_sub = self.create_subscription(ModeStatus, '/control_mode_status', self.update_mode, 10)

        self.vosk_model = Model("/home/david/Projects/Tello_mr_ros_ws/src/tello_mixed_reality_handcontrol/vosk-model-small-en-us-0.15")
        self.recognizer = KaldiRecognizer(self.vosk_model, 16000)

        self.alien_image = cv2.imread('/home/david/Projects/Tello_mr_ros_ws/src/tello_mixed_reality_handcontrol/images/alien.png', cv2.IMREAD_UNCHANGED)
        self.dead_alien_image = cv2.imread('/home/david/Projects/Tello_mr_ros_ws/src/tello_mixed_reality_handcontrol/images/dead_alien.png', cv2.IMREAD_UNCHANGED)

        pygame.init()
        pygame.mixer.init()
        self.gun_sound = pygame.mixer.Sound('/home/david/Projects/Tello_mr_ros_ws/src/tello_mixed_reality_handcontrol/sound/gun.wav')
        self.reload_sound = pygame.mixer.Sound('/home/david/Projects/Tello_mr_ros_ws/src/tello_mixed_reality_handcontrol/sound/reload.wav')


        self.dead_targets = set()
        self.alive_targets = set()
        self.score = 0
        self.magazine = 10
        self.shoot_pressed = False 
        self.reload_pressed = False
        self.game_mode = "GAMEOFF"
        self.ps4_on = False
        # Game Logs Variables
        self.game_start_time = None
        self.game_end_time = None
        self.total_shots_fired = 0
        self.hit_timestamps = []
        self.reload_timestamps = []
        self.shoot_timestamps = []

        self.prev_shoot_button = False
        self.prev_reload_button = False

        self.dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        self.parameters = aruco.DetectorParameters()

        self.camera_pub = self.create_publisher(Image, '/camera/game_image', 10)
        self.game_status_pub = self.create_publisher(GameStatus, '/game/status', 10)

        self.audio_thread = threading.Thread(target=self.listen_for_commands)
        self.audio_thread.daemon = True
        self.audio_thread.start()

    def image_callback(self, msg):
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = aruco.detectMarkers(gray, self.dictionary, parameters=self.parameters)

        remaining_time = 0
        if self.game_mode == "GAMEON" and self.game_start_time:
            elapsed_time = datetime.now().timestamp() - self.game_start_time
            remaining_time = max(0, int(300 - elapsed_time))
            minutes = remaining_time // 60
            seconds = remaining_time % 60
            formatted_time = f"{minutes:02}:{seconds:02}"
            if elapsed_time >= 300:
                self.get_logger().info("Timeout -- GAME OVER!")
                self.game_end_time = int(datetime.now().timestamp() * 1000)
                self.log_game_session()
                self.game_mode = "GAMEOFF"
                self.game_start_time = None
                return

        if self.ps4_on:
            self.magazine = min(self.magazine, 1)


        h, w = frame.shape[:2]
        center_screen = (w // 2, h // 2)

        hit_positions = []

        if ids is not None:
            ids = ids.flatten()
            for corner, marker_id in zip(corners, ids):
                self.alive_targets.add(marker_id)

                aruco.drawDetectedMarkers(frame, [corner])

                c = corner[0]
                center_x, center_y = c[:, 0].mean(), c[:, 1].mean()
                enemy_center = (int(center_x), int(center_y))

                s1 = np.linalg.norm(c[0] - c[1])
                s2 = np.linalg.norm(c[1] - c[2])
                s3 = np.linalg.norm(c[2] - c[3])
                s4 = np.linalg.norm(c[3] - c[0])
                marker_size = int(np.mean([s1, s2, s3, s4]))

                top_left_x = int(center_x - marker_size / 2)
                top_left_y = int(center_y - marker_size / 2)

                if marker_id in self.dead_targets:
                    resized_img = cv2.resize(self.dead_alien_image, (marker_size, marker_size), interpolation=cv2.INTER_AREA)
                else:
                    resized_img = cv2.resize(self.alien_image, (marker_size, marker_size), interpolation=cv2.INTER_AREA)
                self.overlay_image_alpha(frame, resized_img, top_left_x, top_left_y)

        if self.shoot_pressed and not self.prev_shoot_button and self.magazine > 0:
            self.gun_sound.play()
            self.shoot_pressed = False

            self.magazine -= 1
            self.total_shots_fired += 1

            self.shoot_timestamps.append(int(datetime.now().timestamp() * 1000))
            
            self.get_logger().info("SHOOTING")

            if ids is not None:
                ids = ids.flatten()
                for corner, marker_id in zip(corners, ids):
                    if marker_id not in self.alive_targets:
                        continue

                    c = corner[0]
                    center_x, center_y = c[:, 0].mean(), c[:, 1].mean()
                    enemy_center = (int(center_x), int(center_y))
                    dist = np.linalg.norm(np.array(center_screen) - np.array(enemy_center))

                    if dist < 30:
                        self.alive_targets.remove(marker_id)
                        self.dead_targets.add(marker_id)
                        hit_positions.append(enemy_center)
                        self.score += 1
                        self.get_logger().info(f"Target hit!") 
                        self.hit_timestamps.append({"id": marker_id,"timestamp": int(datetime.now().timestamp()*1000)})

                        if len(self.dead_targets) >= 3:
                            self.game_end_time = int(datetime.now().timestamp())*1000
                            self.log_game_session()
                            self.game_mode = "GAMEOFF"
                            self.game_start_time = None
                            return

        elif self.shoot_pressed:
            self.get_logger().info(f"Reload!")

        if self.reload_pressed and self.prev_reload_button and self.magazine < 10:
            self.reload_sound.play()

            self.reload_timestamps.append(int(datetime.now().timestamp()*1000))

            self.get_logger().info("RELOADING")

            self.magazine = 1 if self.ps4_on else 10
            self.get_logger().info(f"Reloading!")
            self.reload_pressed = False
        
        self.prev_shoot_button = self.shoot_pressed
        self.prev_reload_button = self.reload_pressed
        
        cv2.drawMarker(frame, center_screen, (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=25, thickness=2)

        ros_image = self.bridge.cv2_to_imgmsg(frame, encoding='bgr8')
        ros_image.header.stamp = self.get_clock().now().to_msg()
        ros_image.header.frame_id = "tello_game"
        self.camera_pub.publish(ros_image)


        game_status_msg = GameStatus()
        game_status_msg.score = self.score
        game_status_msg.magazine = self.magazine
        game_status_msg.total_targets = len(self.alive_targets) + self.score
        game_status_msg.alive_targets = len(self.alive_targets)
        game_status_msg.hit_targets = self.score
        game_status_msg.remaining_time = remaining_time
        game_status_msg.formatted_time = formatted_time if self.game_mode == "GAMEON" else "00:00"

        self.game_status_pub.publish(game_status_msg)


    def ps4_button_callback(self, msg):
        """
        Callback function to handle PS4 button presses.
        """
        if self.game_mode == "GAMEOFF" or not self.ps4_on:
            return
        
        self.shoot_pressed = msg.buttons[7] == 1
        self.reload_pressed = msg.buttons[6] == 1
        #self.get_logger().info("PS4 shoot")
    
    def update_trigger_state(self, msg):
        """
        Update the shoot and reload states based on the received message.
        """
        if self.game_mode == "GAMEOFF":
            return
        self.shoot_pressed = msg.state == 1
        self.reload_pressed = msg.state == 2
        #self.get_logger().info("Shoot")

    def update_mode(self, msg):
        """
        Update the mode based on the received message.
        """
        mode_map = {
            0: "DEFAULT",
            1: "MPU",
            2: "PS4",
            3: "PHONEIMU"
        }
        game_mode_map = {
            0: "GAMEOFF",
            1: "GAMEON"
        }

        new_game_mode = game_mode_map.get(msg.game_mode, "Unknown")

        if new_game_mode == "GAMEON" and self.game_mode != "GAMEON":
            self.game_start_time = datetime.now().timestamp()
            self.game_end_time = None

        self.game_mode = new_game_mode
        self.ps4_on = mode_map.get(msg.mode, "Unknown") == "PS4"

    def listen_for_commands(self):
        """
        Listen for voice commands using Vosk and sounddevice.
        Commands: "shoot" and "reload"
        """

        q = queue.Queue()
        def callback(indata, frames, time, status):
            if status:
                self.get_logger().info(status)
            q.put(bytes(indata))
        
        with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype='int16',
                            channels=1, callback=callback):
            self.get_logger().info("Listening... (say 'shoot' or 'reload')")

            while True:
                data = q.get()
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "")
                    self.get_logger().info(f"You said: {text}") 

                    if "shoot" in text and self.game_mode == "GAMEON":
                        self.get_logger().info("SHOOT detected!")
                        self.shoot_pressed = True
                    elif "reload" in text and self.game_mode == "GAMEON":
                        self.get_logger().info("RELOAD detected!")
                        self.reload_pressed = True

    def overlay_image_alpha(self, background, overlay, x, y):
        """
        Overlay an image with alpha channel onto a background image at specified coordinates.
        """

        bh, bw = background.shape[:2]
        h, w = overlay.shape[:2]

        if x < 0:
            overlay = overlay[:, -x:]
            w = overlay.shape[1]
            x = 0
        if y < 0:
            overlay = overlay[-y:, :]
            h = overlay.shape[0]
            y = 0
        if x + w > bw:
            overlay = overlay[:, :bw - x]
            w = overlay.shape[1]
        if y + h > bh:
            overlay = overlay[:bh - y, :]
            h = overlay.shape[0]

        if overlay.shape[2] != 4:
            return

        alpha_overlay = overlay[:, :, 3] / 255.0
        alpha_background = 1.0 - alpha_overlay

        for c in range(3):
            background[y:y+h, x:x+w, c] = (
                alpha_overlay * overlay[:, :, c] +
                alpha_background * background[y:y+h, x:x+w, c]
            )

    def log_game_session(self):
        if self.game_start_time and self.game_end_time:
            timestamp = int(self.game_end_time)
            date_str = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d')
            filename = f'/home/david/Projects/Tello_mr_ros_ws/src/tello_mixed_reality_handcontrol/game_logs/game_log_{date_str}_{timestamp}.csv'

            events = []

            events.append(("Game_Start_Time", int(self.game_start_time*1000),""))

            for hit in self.hit_timestamps:
                events.append(("Target_Hit", int(hit['timestamp']), f"ID {hit['id']}"))

            for reload_time in self.reload_timestamps:
                events.append(("Reload", int(reload_time),""))

            for shoot_time in self.shoot_timestamps:
                events.append(("Shot_Fired", int(shoot_time),""))

            events.append(("Game_End_Time", int(self.game_end_time),""))
            events.append(("Score", self.score,""))
            events.append(("Total_Shots_Fired", self.total_shots_fired,""))

            events.sort(key=lambda e: e[1])

            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Event", "Timestamp", "Details"])
                for event, timestamp, details in events:
                    writer.writerow([event, timestamp,details])

            
            self.hit_timestamps = []
            self.reload_timestamps = []
            self.shoot_timestamps = []
            self.total_shots_fired = 0
