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
            self.__device_url = mqtt_config['device_url']
        except Exception as e:
            self.__logger.error("MQTT not set up because of: {}".format(e))
            raise

    def start(self):
        try:
            self.__controller.publish_state = self.publish_state
            self.__client.loop_start()
        except Exception as e:
            self.__logger.error("MQTT not started because of: {}".format(e))
            raise

    def stop(self):
        try:
            self.__controller.publish_state = None
            self.__client.loop_stop()
        except Exception as e:
            self.__logger.error("MQTT stopping failed because of: {}".format(e))


    def on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            self.__logger.warning("Can't connect with mqtt broker. Reason = {0}".format(rc))
            return
        self.__logger.info('Connected with mqtt broker')

        # send last will and testament
        available_topic = "homeassistant/switch/" + self.__device_id + "/available"
        client.publish(available_topic, "online", qos=0, retain=True)

        ## sensors
        self.__setup_sensor(client, "date_from", "mdi:calendar-arrow-left", available_topic, entity_category="config")
        self.__setup_sensor(client, "date_to", "mdi:calendar-arrow-right", available_topic, entity_category="config")
        self.__setup_sensor(client, "location_filter", "mdi:map-search", available_topic, entity_category="config")
        self.__setup_sensor(client, "tags_filter", "mdi:image-search", available_topic, entity_category="config")
        self.__setup_sensor(client, "image_counter", "mdi:camera-burst", available_topic, entity_category="diagnostic")
        self.__setup_sensor(client, "image", "mdi:file-image", available_topic, has_attributes=True, entity_category="diagnostic")

        ## numbers
        self.__setup_number(client, "brightness", 0.0, 1.0, 0.1, "mdi:brightness-6", available_topic)
        self.__setup_number(client, "time_delay", 1, 400, 1, "mdi:image-plus", available_topic)
        self.__setup_number(client, "fade_time", 1, 50, 1,"mdi:image-size-select-large", available_topic)
        self.__setup_number(client, "matting_images", 0.0, 1.0, 0.01, "mdi:image-frame", available_topic)

        ## selects
        _, dir_list = self.__controller.get_directory_list()
        dir_list.sort()
        self.__setup_select(client, "directory", dir_list, "mdi:folder-multiple-image", available_topic, init=True)
        command_topic = self.__device_id + "/directory"
        client.subscribe(command_topic, qos=0)

        ## switches
        self.__setup_switch(client, "_text_refresh", "mdi:refresh", available_topic, entity_category="config")
        self.__setup_switch(client, "_name_toggle", "mdi:subtitles", available_topic,
                            self.__controller.text_is_on("name"), entity_category="config")
        self.__setup_switch(client, "_title_toggle", "mdi:subtitles", available_topic,
                            self.__controller.text_is_on("title"), entity_category="config")
        self.__setup_switch(client, "_caption_toggle", "mdi:subtitles", available_topic,
                            self.__controller.text_is_on("caption"), entity_category="config")
        self.__setup_switch(client, "_date_toggle", "mdi:calendar-today", available_topic,
                            self.__controller.text_is_on("date"), entity_category="config")
        self.__setup_switch(client, "_location_toggle", "mdi:crosshairs-gps", available_topic,
                            self.__controller.text_is_on("location"), entity_category="config")
        self.__setup_switch(client, "_directory_toggle", "mdi:folder", available_topic,
                            self.__controller.text_is_on("directory"), entity_category="config")
        self.__setup_switch(client, "_text_off", "mdi:badge-account-horizontal-outline", available_topic, entity_category="config")
        self.__setup_switch(client, "_display", "mdi:panorama", available_topic,
                            self.__controller.display_is_on)
        self.__setup_switch(client, "_clock", "mdi:clock-outline", available_topic,
                            self.__controller.clock_is_on, entity_category="config")
        self.__setup_switch(client, "_shuffle", "mdi:shuffle-variant", available_topic,
                            self.__controller.shuffle)
        self.__setup_switch(client, "_paused", "mdi:pause", available_topic,
                            self.__controller.paused)

        # buttons
        self.__setup_button(client, "_delete", "mdi:delete", available_topic)
        self.__setup_button(client, "_back", "mdi:skip-previous", available_topic)
        self.__setup_button(client, "_next", "mdi:skip-next", available_topic)

        client.subscribe(self.__device_id + "/purge_files", qos=0) # close down without killing!
        client.subscribe(self.__device_id + "/stop", qos=0) # close down without killing!

    def __setup_sensor(self, client, topic, icon, available_topic, has_attributes=False, entity_category=None):
        sensor_topic_head = "homeassistant/sensor/" + self.__device_id
        config_topic = sensor_topic_head + "_" + topic + "/config"
        name = self.__device_id + "_" + topic
        dict = {"name": name,
                "icon": icon,
                "value_template": "{{ value_json." + topic + "}}",
                "avty_t": available_topic,
                "uniq_id": name,
                "dev":{"ids":[self.__device_id]}}
        if has_attributes == True:
            dict["state_topic"] = sensor_topic_head + "_" + topic + "/state"
            dict["json_attributes_topic"] = sensor_topic_head + "_" + topic + "/attributes"
        else:
            dict["state_topic"] = sensor_topic_head + "/state"
        if entity_category:
            dict["entity_category"] = entity_category
                                     
        config_payload = json.dumps(dict)
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.subscribe(self.__device_id + "/" + topic, qos=0)

    def __setup_number(self, client, topic, min, max, step, icon, available_topic):
        number_topic_head = "homeassistant/number/" + self.__device_id
        config_topic = number_topic_head + "_" + topic + "/config"
        command_topic = self.__device_id + "/" + topic
        state_topic = "homeassistant/sensor/" + self.__device_id + "/state"
        name = self.__device_id + "_" + topic
        config_payload = json.dumps({"name": name,
                                    "min": min,
                                    "max": max,
                                    "step": step,
                                    "icon": icon,
                                    "entity_category": "config",
                                    "state_topic": state_topic,
                                    "command_topic": command_topic,
                                    "value_template": "{{ value_json." + topic + "}}",
                                    "avty_t": available_topic,
                                    "uniq_id": name,
                                    "dev":{"ids":[self.__device_id]}})
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.subscribe(command_topic, qos=0)

    def __setup_select(self, client, topic, options, icon, available_topic, init=False):
        select_topic_head = "homeassistant/select/" + self.__device_id
        config_topic = select_topic_head + "_" + topic + "/config"
        command_topic = self.__device_id + "/" + topic
        state_topic = "homeassistant/sensor/" + self.__device_id + "/state"
        name = self.__device_id + "_" + topic

        config_payload = json.dumps({"name": name,
                                    "entity_category": "config",
                                    "icon": icon,
                                    "options": options,
                                    "state_topic": state_topic,
                                    "command_topic": command_topic,
                                    "value_template": "{{ value_json." + topic + "}}",
                                    "avty_t": available_topic,
                                    "uniq_id": name,
                                    "dev":{"ids":[self.__device_id]}})
        client.publish(config_topic, config_payload, qos=0, retain=True)
        if init:
            client.subscribe(command_topic, qos=0)

    def __setup_switch(self, client, topic, icon,
                       available_topic, is_on=False, entity_category=None):
        switch_topic_head = "homeassistant/switch/" + self.__device_id
        config_topic = switch_topic_head + topic + "/config"
        command_topic = switch_topic_head + topic + "/set"
        state_topic = switch_topic_head + topic + "/state"
        dict = {"name": self.__device_id + topic,
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
                "mf": "pi3d PictureFrame project"}}
        if self.__device_url :
            dict["dev"]["cu"] = self.__device_url
        if entity_category:
            dict["entity_category"] = entity_category
        config_payload = json.dumps(dict)

        client.subscribe(command_topic , qos=0)
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.publish(state_topic, "ON" if is_on else "OFF", qos=0, retain=True)

    def __setup_button(self, client, topic, icon,
                       available_topic, entity_category=None):
        button_topic_head = "homeassistant/button/" + self.__device_id
        config_topic = button_topic_head + topic + "/config"
        command_topic = button_topic_head + topic + "/set"
        dict = {"name": self.__device_id + topic,
                "icon": icon,
                "command_topic": command_topic,
                "payload_press": "ON",
                "avty_t": available_topic,
                "uniq_id": self.__device_id + topic,
                "dev": {
                "ids": [self.__device_id],
                "name": self.__device_id,
                "mdl": "PictureFrame",
                "sw": __version__,
                "mf": "pi3d PictureFrame project"}}
        if self.__device_url :
            dict["dev"]["cu"] = self.__device_url
        if entity_category:
            dict["entity_category"] = entity_category
        config_payload = json.dumps(dict)

        client.subscribe(command_topic , qos=0)
        client.publish(config_topic, config_payload, qos=0, retain=True)

    def on_message(self, client, userdata, message):
        msg = message.payload.decode("utf-8")
        switch_topic_head = "homeassistant/switch/" + self.__device_id
        button_topic_head = "homeassistant/button/" + self.__device_id

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
        # clock
        if message.topic == switch_topic_head + "_clock/set":
            state_topic = switch_topic_head + "_clock/state"
            if msg == "ON":
                self.__controller.clock_is_on = True
                client.publish(state_topic, "ON", retain=True)
            elif msg == "OFF":
                self.__controller.clock_is_on = False
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
        elif message.topic == button_topic_head + "_back/set":
            if msg == "ON":
                self.__controller.back()
        # next buttons
        elif message.topic == button_topic_head + "_next/set":
            if msg == "ON":
                self.__controller.next()
        # delete
        elif message.topic == button_topic_head + "_delete/set":
            if msg == "ON":
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
                self.__controller.set_show_text("folder", msg)
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
        # matting_images
        elif message.topic == self.__device_id + "/matting_images":
            self.__logger.info("Received matting_images: %s", msg)
            self.__controller.matting_images = float(msg)
        # location filter
        elif message.topic == self.__device_id + "/location_filter":
            self.__logger.info("Recieved location filter: %s", msg)
            self.__controller.location_filter = msg
        # tags filter
        elif message.topic == self.__device_id + "/tags_filter":
            self.__logger.info("Recieved tags filter: %s", msg)
            self.__controller.tags_filter = msg

        # set the flag to purge files from database
        elif message.topic == self.__device_id + "/purge_files":
            self.__controller.purge_files()

        # stop loops and end program
        elif message.topic == self.__device_id + "/stop":
            self.__controller.stop()

    def publish_state(self, image=None, image_attr=None):
        sensor_topic_head = "homeassistant/sensor/" + self.__device_id
        switch_topic_head = "homeassistant/switch/" + self.__device_id
        available_topic = switch_topic_head + "/available"

        sensor_state_payload = {}
        image_state_payload = {}

        ## image
        # image attributes
        if image_attr is not None:
            attributes_topic = sensor_topic_head + "_image/attributes"
            self.__logger.debug("Send image attributes: %s", image_attr)
            self.__client.publish(attributes_topic, json.dumps(image_attr), qos=0, retain=False)
        # image sensor
        if image is not None:
            _, tail = os.path.split(image)
            image_state_payload["image"] = tail
            image_state_topic = sensor_topic_head + "_image/state"
            self.__logger.info("Send image state: %s", image_state_payload)
            self.__client.publish(image_state_topic, json.dumps(image_state_payload), qos=0, retain=False)

        ## sensor
        # directory sensor
        actual_dir, dir_list = self.__controller.get_directory_list()
        sensor_state_payload["directory"] = actual_dir
        # image counter sensor
        sensor_state_payload["image_counter"] = str(self.__controller.get_number_of_files())
        # date_from
        sensor_state_payload["date_from"] = int(self.__controller.date_from)
        # date_to
        sensor_state_payload["date_to"] = int(self.__controller.date_to)
        # location_filter
        sensor_state_payload["location_filter"] = self.__controller.location_filter
        # tags_filter
        sensor_state_payload["tags_filter"] = self.__controller.tags_filter
        ## number state
        # time_delay
        sensor_state_payload["time_delay"] = self.__controller.time_delay
        # fade_time
        sensor_state_payload["fade_time"] = self.__controller.fade_time
        # brightness
        sensor_state_payload["brightness"] = self.__controller.brightness
        # matting_images
        sensor_state_payload["matting_images"] = self.__controller.matting_images

        #pulish sensors
        dir_list.sort()
        self.__setup_select(self.__client, "directory", dir_list, "mdi:folder-multiple-image", available_topic, init=False)

        self.__logger.info("Send sensor state: %s", sensor_state_payload)
        sensor_state_topic = sensor_topic_head + "/state"
        self.__client.publish(sensor_state_topic, json.dumps(sensor_state_payload), qos=0, retain=False)

        # publish state of switches
        # pause
        state_topic = switch_topic_head + "_paused/state"
        payload = "ON" if self.__controller.paused else "OFF"
        self.__client.publish(state_topic, payload, retain=True)
        # shuffle
        state_topic = switch_topic_head + "_shuffle/state"
        payload = "ON" if self.__controller.shuffle else "OFF"
        self.__client.publish(state_topic, payload, retain=True)
        # display
        state_topic = switch_topic_head + "_display/state"
        payload = "ON" if self.__controller.display_is_on else "OFF"
        self.__client.publish(state_topic, payload, retain=True)

        # send last will and testament
        self.__client.publish(available_topic, "online", qos=0, retain=True)

