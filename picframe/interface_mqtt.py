"""MQTT interface of picframe."""

import logging
import time
import paho.mqtt.client as mqtt
import json
import os
from picframe import __version__


class InterfaceMQTT:
    """MQTT interface of picframe.
    
    This interface interacts via mqtt with the user to steer the image display.

    Attributes
    ----------
    controller : Controler 
        Controller for picframe
   

    Methods
    -------

    """

    def __init__(self, controller, mqtt_config):
        self.__logger = logging.getLogger("interface_mqtt.InterfaceMQTT")
        self.__logger.info('creating an instance of InterfaceMQTT')
        self.__controller = controller
        try:
            device_id = mqtt_config['device_id']
            self.__client = mqtt.Client(client_id = device_id, clean_session=True)
            login = mqtt_config['login']
            password = mqtt_config['password']
            self.__client.username_pw_set(login, password) 
            tls = mqtt_config['tls']
            if tls:
                self.__client.tls_set(tls)
            server = mqtt_config['server']
            port = mqtt_config['port']
            self.__client.connect(server, port, 60) 
            self.__client.will_set("homeassistant/switch/" + mqtt_config['device_id'] + "/available", "offline", qos=0, retain=True)
            self.__client.on_connect = self.on_connect
            self.__client.on_message = self.on_message
            self.__device_id = mqtt_config['device_id']
        except Exception as e:
            self.__logger.info("MQTT not set up because of: {}".format(e))
    
    def start(self):
        try:
            self.__controller.publish_state = self.publish_state
            self.__client.loop_start()
        except Exception as e:
            self.__logger.info("MQTT not started because of: {}".format(e))

    def stop(self):
        try:
            self.__controller.publish_state = None
            self.__client.loop_stop()
        except Exception as e:
            self.__logger.info("MQTT stopping failed because of: {}".format(e))


    def on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            self.__logger.warning("Can't connect with mqtt broker. Reason = {0}".format(rc))   
            return 
        self.__logger.info('Connected with mqtt broker')

        sensor_topic_head = "homeassistant/sensor/" + self.__device_id
        switch_topic_head = "homeassistant/switch/" + self.__device_id

        # send last will and testament
        available_topic = switch_topic_head + "/available"
        client.publish(available_topic, "online", qos=0, retain=True)

        # state_topic for all picframe sensors
        state_topic = sensor_topic_head + "/state"

        ## sensors
        self.__setup_sensor(client, sensor_topic_head, "date_from", "mdi:calendar-arrow-left", available_topic)
        self.__setup_sensor(client, sensor_topic_head, "date_to", "mdi:calendar-arrow-right", available_topic)
        self.__setup_sensor(client, sensor_topic_head, "time_delay", "mdi:image-plus", available_topic)
        self.__setup_sensor(client, sensor_topic_head, "brightness", "mdi:brightness-6", available_topic)
        self.__setup_sensor(client, sensor_topic_head, "fade_time", "mdi:image-size-select-large", available_topic)
        self.__setup_sensor(client, sensor_topic_head, "location_filter", "mdi:map-search", available_topic)
        self.__setup_sensor(client, sensor_topic_head, "tags_filter", "mdi:image-search", available_topic)
        self.__setup_sensor(client, sensor_topic_head, "image_counter", "mdi:camera-burst", available_topic)
        self.__setup_sensor(client, sensor_topic_head, "image", "mdi:file-image", available_topic, has_attributes=True)
        self.__setup_sensor(client, sensor_topic_head, "directory", "mdi:folder-multiple-image", available_topic, has_attributes=True)

        ## switches
        self.__setup_switch(client, switch_topic_head, "_text_refresh", "mdi:refresh", available_topic)
        self.__setup_switch(client, switch_topic_head, "_delete", "mdi:delete", available_topic)
        self.__setup_switch(client, switch_topic_head, "_name_toggle", "mdi:subtitles", available_topic,
                            self.__controller.text_is_on("name"))
        self.__setup_switch(client, switch_topic_head, "_title_toggle", "mdi:subtitles", available_topic,
                            self.__controller.text_is_on("title"))
        self.__setup_switch(client, switch_topic_head, "_caption_toggle", "mdi:subtitles", available_topic,
                            self.__controller.text_is_on("caption"))
        self.__setup_switch(client, switch_topic_head, "_date_toggle", "mdi:calendar-today", available_topic,
                            self.__controller.text_is_on("date"))
        self.__setup_switch(client, switch_topic_head, "_location_toggle", "mdi:crosshairs-gps", available_topic,
                            self.__controller.text_is_on("location"))
        self.__setup_switch(client, switch_topic_head, "_directory_toggle", "mdi:folder", available_topic,
                            self.__controller.text_is_on("directory"))
        self.__setup_switch(client, switch_topic_head, "_text_off", "mdi:badge-account-horizontal-outline", available_topic)
        self.__setup_switch(client, switch_topic_head, "_display", "mdi:panorama", available_topic,
                            self.__controller.display_is_on)
        self.__setup_switch(client, switch_topic_head, "_shuffle", "mdi:shuffle-variant", available_topic,
                            self.__controller.shuffle)
        self.__setup_switch(client, switch_topic_head, "_paused", "mdi:pause", available_topic,
                            self.__controller.paused)
        self.__setup_switch(client, switch_topic_head, "_back", "mdi:skip-previous", available_topic)
        self.__setup_switch(client, switch_topic_head, "_next", "mdi:skip-next", available_topic)

        client.subscribe(self.__device_id + "/stop", qos=0) # close down without killing!

    def __setup_sensor(self, client, sensor_topic_head, topic, icon, available_topic, has_attributes=False):
        config_topic = sensor_topic_head + "_" + topic + "/config"
        name = self.__device_id + "_" + topic
        if has_attributes == True:
            config_payload = json.dumps({"name": name,
                                     "icon": icon,
                                     "state_topic": sensor_topic_head + "/state",
                                     "value_template": "{{ value_json." + topic + "}}",
                                     "avty_t": available_topic,
                                     "json_attributes_topic": sensor_topic_head + "_" + topic + "/attributes",
                                     "uniq_id": name,
                                     "dev":{"ids":[self.__device_id]}})
        else:
            config_payload = json.dumps({"name": name,
                                     "icon": icon,
                                     "state_topic": sensor_topic_head + "/state",
                                     "value_template": "{{ value_json." + topic + "}}",
                                     "avty_t": available_topic,
                                     "uniq_id": name,
                                     "dev":{"ids":[self.__device_id]}})
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.subscribe(self.__device_id + "/" + topic, qos=0)

    def __setup_switch(self, client, switch_topic_head, topic, icon,
                       available_topic, is_on=False):
        config_topic = switch_topic_head + topic + "/config"
        command_topic = switch_topic_head + topic + "/set"
        state_topic = switch_topic_head + topic + "/state"
        config_payload = json.dumps({"name": self.__device_id + topic,
                                     "icon": icon,
                                     "command_topic": command_topic,
                                     "state_topic": state_topic,
                                     "avty_t": available_topic,
                                     "uniq_id": self.__device_id + topic,
                                     "dev": {
                                        "ids": [self.__device_id], 
                                        "name": self.__device_id, 
                                        "mdl": "PictureFrame", 
                                        "sw": __version__, 
                                        "mf": "pi3d PictureFrame project"}})
      
        client.subscribe(command_topic , qos=0)
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.publish(state_topic, "ON" if is_on else "OFF", qos=0, retain=True)

    def on_message(self, client, userdata, message):
        msg = message.payload.decode("utf-8") 
        switch_topic_head = "homeassistant/switch/" + self.__device_id
       
        ###### switches ######
        # display
        if message.topic == switch_topic_head + "_display/set":
            state_topic = switch_topic_head + "_display/state"
            if msg == "ON":
                self.__controller.display_is_on = True
                client.publish(state_topic, "ON", retain=True)
            elif msg == "OFF":
                self.__controller.display_is_on = False
                client.publish(state_topic, "OFF", retain=True)
        # shuffle
        elif message.topic == switch_topic_head + "_shuffle/set":
            state_topic = switch_topic_head + "_shuffle/state"
            if msg == "ON":
                self.__controller.shuffle = True
                client.publish(state_topic, "ON", retain=True)
            elif msg == "OFF":
                self.__controller.shuffle = False
                client.publish(state_topic, "OFF", retain=True)
        # paused
        elif message.topic == switch_topic_head + "_paused/set":
            state_topic = switch_topic_head + "_paused/state"
            if msg == "ON":
                self.__controller.paused = True
                client.publish(state_topic, "ON", retain=True)
            elif msg == "OFF":
                self.__controller.paused = False
                client.publish(state_topic, "OFF", retain=True)
        # back buttons
        elif message.topic == switch_topic_head + "_back/set":
            state_topic = switch_topic_head + "_back/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.__controller.back()
        # next buttons
        elif message.topic == switch_topic_head + "_next/set":
            state_topic = switch_topic_head + "_next/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.__controller.next()
        # delete
        elif message.topic == switch_topic_head + "_delete/set":
            state_topic = switch_topic_head + "_delete/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.__controller.delete()
        # title on
        elif message.topic == switch_topic_head + "_title_toggle/set":
            state_topic = switch_topic_head + "_title_toggle/state"
            if msg in ("ON", "OFF"):
                self.__controller.set_show_text("title", msg)
                client.publish(state_topic, msg, retain=True)
        # caption on
        elif message.topic == switch_topic_head + "_caption_toggle/set":
            state_topic = switch_topic_head + "_caption_toggle/state"
            if msg in ("ON", "OFF"):
                self.__controller.set_show_text("caption", msg)
                client.publish(state_topic, msg, retain=True)
        # name on
        elif message.topic == switch_topic_head + "_name_toggle/set":
            state_topic = switch_topic_head + "_name_toggle/state"
            if msg in ("ON", "OFF"):
                self.__controller.set_show_text("name", msg)
                client.publish(state_topic, msg, retain=True)
        # date_on
        elif message.topic == switch_topic_head + "_date_toggle/set":
            state_topic = switch_topic_head + "_date_toggle/state"
            if msg in ("ON", "OFF"):
                self.__controller.set_show_text("date", msg)
                client.publish(state_topic, msg, retain=True)
        # location_on
        elif message.topic == switch_topic_head + "_location_toggle/set":
            state_topic = switch_topic_head + "_location_toggle/state"
            if msg in ("ON", "OFF"):
                self.__controller.set_show_text("location", msg)
                client.publish(state_topic, msg, retain=True)
        # directory_on
        elif message.topic == switch_topic_head + "_directory_toggle/set":
            state_topic = switch_topic_head + "_directory_toggle/state"
            if msg in ("ON", "OFF"):
                self.__controller.set_show_text("directory", msg)
                client.publish(state_topic, msg, retain=True)
        # text_off
        elif message.topic == switch_topic_head + "_text_off/set":
            state_topic = switch_topic_head + "_text_off/state"
            if msg == "ON":
                self.__controller.set_show_text()
                client.publish(state_topic, "OFF", retain=True)
                state_topic = switch_topic_head + "_directory_toggle/state"
                client.publish(state_topic, "OFF", retain=True)
                state_topic = switch_topic_head + "_location_toggle/state"
                client.publish(state_topic, "OFF", retain=True)
                state_topic = switch_topic_head + "_date_toggle/state"
                client.publish(state_topic, "OFF", retain=True)
                state_topic = switch_topic_head + "_name_toggle/state"
                client.publish(state_topic, "OFF", retain=True)
                state_topic = switch_topic_head + "_title_toggle/state"
                client.publish(state_topic, "OFF", retain=True)
                state_topic = switch_topic_head + "_caption_toggle/state"
                client.publish(state_topic, "OFF", retain=True)
        # text_refresh
        elif message.topic == switch_topic_head + "_text_refresh/set":
            state_topic = switch_topic_head + "_text_refresh/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.__controller.refresh_show_text()

        ##### values ########
        # change subdirectory
        elif message.topic == self.__device_id + "/directory":
            self.__logger.info("Recieved subdirectory: %s", msg)
            self.__controller.subdirectory = msg
        # date_from
        elif message.topic == self.__device_id + "/date_from":
            self.__logger.info("Recieved date_from: %s", msg)
            self.__controller.date_from = msg
        # date_to
        elif message.topic == self.__device_id + "/date_to":
            self.__logger.info("Recieved date_to: %s", msg)
            self.__controller.date_to = msg
        # fade_time
        elif message.topic == self.__device_id + "/fade_time":
            self.__logger.info("Recieved fade_time: %s", msg)
            self.__controller.fade_time = float(msg)
        # time_delay
        elif message.topic == self.__device_id + "/time_delay":
            self.__logger.info("Recieved time_delay: %s", msg)
            self.__controller.time_delay = float(msg)
        # brightness
        elif message.topic == self.__device_id + "/brightness":
            self.__logger.info("Recieved brightness: %s", msg)
            self.__controller.brightness = float(msg)
        # location filter
        elif message.topic == self.__device_id + "/location_filter":
            self.__logger.info("Recieved location filter: %s", msg)
            self.__controller.location_filter = msg
        # tags filter
        elif message.topic == self.__device_id + "/tags_filter":
            self.__logger.info("Recieved tags filter: %s", msg)
            self.__controller.tags_filter = msg

        # stop loops and end program
        elif message.topic == self.__device_id + "/stop":
            self.__controller.stop()

    def publish_state(self, image, image_attr):
        topic_head =  "homeassistant/sensor/" + self.__device_id
        switch_topic_head = "homeassistant/switch/" + self.__device_id
        state_topic = topic_head + "/state"
        state_payload = {}
        # directory sensor
        actual_dir, dir_list = self.__controller.get_directory_list()
        state_payload["directory"] = actual_dir
        dir_attr = {}
        dir_attr['directories'] = dir_list
        # image counter sensor
        state_payload["image_counter"] = str(self.__controller.get_number_of_files()) 
        # image sensor
        _, tail = os.path.split(image)
        state_payload["image"] = tail
        # date_from
        state_payload["date_from"] = int(self.__controller.date_from)
        # date_to
        state_payload["date_to"] = int(self.__controller.date_to)
        # time_delay
        state_payload["time_delay"] = self.__controller.time_delay
        # fade_time
        state_payload["fade_time"] = self.__controller.fade_time
        # brightness
        state_payload["brightness"] = self.__controller.brightness
        # location_filter
        state_payload["location_filter"] = self.__controller.location_filter
        # tags_filter
        state_payload["tags_filter"] = self.__controller.tags_filter

        # send last will and testament
        available_topic = switch_topic_head + "/available"
        self.__client.publish(available_topic, "online", qos=0, retain=True)

        #pulish sensors
        attributes_topic = topic_head + "_image/attributes"
        self.__logger.debug("Send image attributes: %s", image_attr)
        self.__client.publish(attributes_topic, json.dumps(image_attr), qos=0, retain=False)
        attributes_topic = topic_head + "_directory/attributes"
        self.__client.publish(attributes_topic, json.dumps(dir_attr), qos=0, retain=False)
        self.__logger.info("Send state: %s", state_payload)
        self.__client.publish(state_topic, json.dumps(state_payload), qos=0, retain=False)
