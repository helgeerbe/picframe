"""Controller of picture_frame."""

import logging
import time
import paho.mqtt.client as mqtt
import json
import os
from picframe import __version__

def make_date(txt):
    dt = txt.replace('/',':').replace('-',':').replace(',',':').replace('.',':').split(':')
    dt_tuple = tuple(int(i) for i in dt) #TODO catch badly formed dates?
    return time.mktime(dt_tuple + (0, 0, 0, 0, 0, 0))

class Controller:
    """Controller of picture_frame.
    
    This controller interacts via mqtt with the user to steer the image display.

    Attributes
    ----------
    model : Model 
        model of picture_frame containing config and business logic
    viewer : ViewerDisplay
        viewer of picture_frame representing the display
   

    Methods
    -------
    paused
        Getter and setter for pausing image display.
    next
        Show next image.
    back
        Show previous image.

    """

    def __init__(self, model, viewer):
        self.__logger = logging.getLogger("controller.Controller")
        self.__logger.info('creating an instance of Controller')
        self.__model = model
        self.__viewer = viewer
        self.__paused = False
        self.__next_tm = 0
        self.__date_from = make_date('1970/1/1')
        self.__date_to = make_date('2038/1/1')

    @property
    def paused(self):
        """Get or set the current state for pausing image display. Setting paused to true
        will show the actual image as long paused is not set to false.
        """
        return self.__paused

    @paused.setter
    def paused(self, val:bool):
        self.__paused = val

    def next(self):
        self.__next_tm = 0

    def back(self):
        self.__model.set_next_file_to_previous_file()
        self.__next_tm = 0

    @property
    def date_from(self):
        return self.__date_from

    @date_from.setter
    def date_from(self, val):
              self.__date_from = val

    @property
    def date_to(self):
        return self.__date_to

    @date_to.setter
    def date_to(self, val):
        self.__date_to = val

    def loop(self):
        next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']
        while True:

            if self.__next_tm == 0:
                time_delay = 1 # must not be 0
                fade_time = 1 # must not be 0
            else:
                time_delay = self.__model.time_delay
                fade_time = self.__model.fade_time

            tm = time.time()
            pics = None #get_next_file returns a tuple of two in case paired portraits have been specified
            if not self.paused and tm > self.__next_tm:
                self.__next_tm = tm + self.__model.time_delay
                pics = self.__model.get_next_file(self.date_from, self.date_to)
                self.publish_sensors(pics[0].fname, pics[0].image_attr)
            if self.__viewer.is_in_transition() == False: # safe to do long running tasks
                if tm > next_check_tm:
                    self.__model.check_for_file_changes()
                    next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']
            if self.__viewer.slideshow_is_running(pics, time_delay, fade_time, self.__paused) == False:
                break


    def start(self):
        try:
            device_id = self.__model.get_mqtt_config()['device_id']
            self.__client = mqtt.Client(client_id = device_id, clean_session=True)
            login = self.__model.get_mqtt_config()['login']
            password = self.__model.get_mqtt_config()['password']
            self.__client.username_pw_set(login, password) 
            tls = self.__model.get_mqtt_config()['tls']
            if tls:
                self.__client.tls_set(tls)
            server = os.path.expanduser(self.__model.get_mqtt_config()['server'])
            port = self.__model.get_mqtt_config()['port']
            self.__client.connect(server, port, 60) 
            self.__client.will_set("homeassistant/switch/" + self.__model.get_mqtt_config()['device_id'] + "/available", "offline", qos=0, retain=True)
            self.__client.on_connect = self.on_connect
            self.__client.on_message = self.on_message
            self.__client.loop_start()
        except Exception as e:
            self.__logger.info("MQTT not set up because of: {}".format(e))
        self.__viewer.slideshow_start()

    def stop(self):
        try:
            self.__client.loop_stop()
        except Exception as e:
            self.__logger.info("MQTT stopping failed because of: {}".format(e))
        self.__viewer.slideshow_stop()

    def on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            self.__logger.warning("Can't connect with mqtt broker. Reason = {0}".format(rc))   
            return 
        self.__logger.info('Connected with mqtt broker')

        device_id = self.__model.get_mqtt_config()['device_id']
        sensor_topic_head = "homeassistant/sensor/" + device_id
        switch_topic_head = "homeassistant/switch/" + device_id

        # send last will and testament
        available_topic = switch_topic_head + "/available"
        client.publish(available_topic, "online", qos=0, retain=True)

        # state_topic for all picframe sensors
        state_topic = sensor_topic_head + "/state"

        # send date_from sensor configuration 
        config_topic = sensor_topic_head + "_date_from/config"
        config_payload = '{"name":"' + device_id + '_date_from", "icon":"mdi:calendar-arrow-left", "state_topic":"' + state_topic + '", "value_template": "{{ value_json.date_from}}", "avty_t":"' + available_topic + '",  "uniq_id":"' + device_id + '_date_from", "dev":{"ids":["' + device_id + '"]}}'
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.subscribe(device_id + "/date_from", qos=0)

        # send date_to sensor configuration 
        config_topic = sensor_topic_head + "_date_to/config"
        config_payload = '{"name":"' + device_id + '_date_to", "icon":"mdi:calendar-arrow-right", "state_topic":"' + state_topic + '", "value_template": "{{ value_json.date_to}}", "avty_t":"' + available_topic + '",  "uniq_id":"' + device_id + '_date_to", "dev":{"ids":["' + device_id + '"]}}'
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.subscribe(device_id + "/date_to", qos=0)

        # send time_delay sensor configuration 
        config_topic = sensor_topic_head + "_time_delay/config"
        config_payload = '{"name":"' + device_id + '_time_delay", "icon":"mdi:image-plus", "state_topic":"' + state_topic + '", "value_template": "{{ value_json.time_delay}}", "avty_t":"' + available_topic + '",  "uniq_id":"' + device_id + '_time_delay", "dev":{"ids":["' + device_id + '"]}}'
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.subscribe(device_id + "/time_delay", qos=0)

        # send brightness sensor configuration 
        config_topic = sensor_topic_head + "_brightness/config"
        config_payload = '{"name":"' + device_id + '_brightness", "icon":"mdi:image-plus", "state_topic":"' + state_topic + '", "value_template": "{{ value_json.brightness}}", "avty_t":"' + available_topic + '",  "uniq_id":"' + device_id + '_brightness", "dev":{"ids":["' + device_id + '"]}}'
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.subscribe(device_id + "/brightness", qos=0)

        # send fade_time sensor configuration 
        config_topic = sensor_topic_head + "_fade_time/config"
        config_payload = '{"name":"' + device_id + '_fade_time", "icon":"mdi:image-size-select-large", "state_topic":"' + state_topic + '", "value_template": "{{ value_json.fade_time}}", "avty_t":"' + available_topic + '",  "uniq_id":"' + device_id + '_fade_time", "dev":{"ids":["' + device_id + '"]}}'
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.subscribe(device_id + "/fade_time", qos=0)

        # send image counter sensor configuration 
        config_topic = sensor_topic_head + "_image_counter/config"
        config_payload = '{"name":"' + device_id + '_image_counter", "icon":"mdi:camera-burst", "state_topic":"' + state_topic + '", "value_template": "{{ value_json.image_counter}}", "avty_t":"' + available_topic + '",  "uniq_id":"' + device_id + '_ic", "dev":{"ids":["' + device_id + '"]}}'
        client.publish(config_topic, config_payload, qos=0, retain=True)

        # send  image sensor configuration
        config_topic = sensor_topic_head + "_image/config"
        attributes_topic = sensor_topic_head + "_image/attributes"
        config_payload = '{"name":"' + device_id + '_image", "icon":"mdi:file-image", "state_topic":"' + state_topic + '",  "value_template": "{{ value_json.image}}", "json_attributes_topic":"' + attributes_topic + '","avty_t":"' + available_topic + '",  "uniq_id":"' + device_id + '_fn", "dev":{"ids":["' + device_id + '"]}}'
        client.publish(config_topic, config_payload, qos=0, retain=True)

        # send  directory sensor configuration
        config_topic = sensor_topic_head + "_dir/config"
        attributes_topic = sensor_topic_head + "_dir/attributes"
        config_payload = '{"name":"' + device_id + '_dir", "icon":"mdi:folder-multiple-image", "state_topic":"' + state_topic + '",  "value_template": "{{ value_json.dir}}", "json_attributes_topic":"' + attributes_topic + '","avty_t":"' + available_topic + '",  "uniq_id":"' + device_id + '_dir", "dev":{"ids":["' + device_id + '"]}}'
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.subscribe(device_id + "/subdirectory", qos=0)

        self.__setup_switch(client, switch_topic_head, device_id, "_text_refresh", "mdi:image-plus", available_topic)
        self.__setup_switch(client, switch_topic_head, device_id, "_delete", "mdi:image-minus", available_topic)
        self.__setup_switch(client, switch_topic_head, device_id, "_name_toggle", "mdi:image-plus", available_topic,
                            self.__viewer.text_is_on("name"))
        self.__setup_switch(client, switch_topic_head, device_id, "_date_toggle", "mdi:image-plus", available_topic,
                            self.__viewer.text_is_on("date"))
        self.__setup_switch(client, switch_topic_head, device_id, "_location_toggle", "mdi:image-plus", available_topic,
                            self.__viewer.text_is_on("location"))
        self.__setup_switch(client, switch_topic_head, device_id, "_directory_toggle", "mdi:image-plus", available_topic,
                            self.__viewer.text_is_on("directory"))
        self.__setup_switch(client, switch_topic_head, device_id, "_text_off", "mdi:image-plus", available_topic)
        self.__setup_switch(client, switch_topic_head, device_id, "_display", "mdi:panorama", available_topic,
                            self.__viewer.display_is_on)
        self.__setup_switch(client, switch_topic_head, device_id, "_shuffle", "mdi:shuffle-variant", available_topic,
                            self.__model.shuffle)
        self.__setup_switch(client, switch_topic_head, device_id, "_paused", "mdi:pause", available_topic,
                            self.paused)
        self.__setup_switch(client, switch_topic_head, device_id, "_back", "mdi:skip-previous", available_topic)
        self.__setup_switch(client, switch_topic_head, device_id, "_next", "mdi:skip-next", available_topic)

    def __setup_switch(self, client, switch_topic_head, device_id, topic, icon,
                       available_topic, is_on=False):
        config_topic = switch_topic_head + topic + "/config"
        command_topic = switch_topic_head + topic + "/set"
        state_topic = switch_topic_head + topic + "/state"
        config_payload = json.dumps({"name": device_id + "_next",
                                     "icon": icon,
                                     "command_topic": command_topic,
                                     "state_topic": state_topic,
                                     "avty_t": available_topic,
                                     "uniq_id": device_id + topic,
                                     "dev": {"ids": [device_id]}})
        client.subscribe(command_topic , qos=0)
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.publish(state_topic, "ON" if is_on else "OFF", qos=0, retain=True)

    def on_message(self, client, userdata, message):
        device_id = self.__model.get_mqtt_config()['device_id']
        msg = message.payload.decode("utf-8") 
        switch_topic_head = "homeassistant/switch/" + device_id
        # these are needed if the text display is changed:
        pic = self.__model.get_current_pics()[0]

        ###### switches ######
        # display
        if message.topic == switch_topic_head + "_display/set":
            state_topic = switch_topic_head + "_display/state"
            if msg == "ON":
                self.__viewer.display_is_on = True
                client.publish(state_topic, "ON", retain=True)
            elif msg == "OFF":
                self.__viewer.display_is_on = False
                client.publish(state_topic, "OFF", retain=True)
        # shuffle
        elif message.topic == switch_topic_head + "_shuffle/set":
            state_topic = switch_topic_head + "_shuffle/state"
            if msg == "ON":
                self.__model.shuffle = True
                client.publish(state_topic, "ON", retain=True)
                self.__viewer.reset_name_tm()
            elif msg == "OFF":
                self.__model.shuffle = False
                client.publish(state_topic, "OFF", retain=True)
        # paused
        elif message.topic == switch_topic_head + "_paused/set":
            state_topic = switch_topic_head + "_paused/state"
            if msg == "ON":
                self.paused = True
                client.publish(state_topic, "ON", retain=True)
                self.__viewer.reset_name_tm(pic, self.paused)
            elif msg == "OFF":
                self.paused = False
                client.publish(state_topic, "OFF", retain=True)
        # back buttons
        elif message.topic == switch_topic_head + "_back/set":
            state_topic = switch_topic_head + "_back/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.back()
                self.__viewer.reset_name_tm()
        # next buttons
        elif message.topic == switch_topic_head + "_next/set":
            state_topic = switch_topic_head + "_next/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.next()
                self.__viewer.reset_name_tm()
        # delete
        elif message.topic == switch_topic_head + "_delete/set":
            state_topic = switch_topic_head + "_delete/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.__model.delete_file()
                self.back() # TODO check needed to avoid skipping one as record has been deleted from model.__file_list
                self.__next_tm = 0
                #TODO rebuild portait pairs as numbers don't match
        # name toggle
        elif message.topic == switch_topic_head + "_name_toggle/set":
            state_topic = switch_topic_head + "_name_toggle/state"
            if msg in ("ON", "OFF"):
                self.__viewer.set_show_text("name", msg)
                client.publish(state_topic, "OFF" if msg == "ON" else "ON", retain=True)
                self.__viewer.reset_name_tm(pic, self.paused)
        # date_on
        elif message.topic == switch_topic_head + "_date_toggle/set":
            state_topic = switch_topic_head + "_date_toggle/state"
            if msg in ("ON", "OFF"):
                self.__viewer.set_show_text("date", msg)
                client.publish(state_topic, msg, retain=True)
                self.__viewer.reset_name_tm(pic, self.paused)
        # location_on
        elif message.topic == switch_topic_head + "_location_toggle/set":
            state_topic = switch_topic_head + "_location_toggle/state"
            if msg in ("ON", "OFF"):
                self.__viewer.set_show_text("location", msg)
                client.publish(state_topic, msg, retain=True)
                self.__viewer.reset_name_tm(pic, self.paused)
        # directory_on
        elif message.topic == switch_topic_head + "_directory_toggle/set":
            state_topic = switch_topic_head + "_directory_toggle/state"
            if msg in ("ON", "OFF"):
                self.__viewer.set_show_text("directory", msg)
                client.publish(state_topic, msg, retain=True)
                self.__viewer.reset_name_tm(pic, self.paused)
        # text_off
        elif message.topic == switch_topic_head + "_text_off/set":
            state_topic = switch_topic_head + "_text_off/state"
            if msg == "ON":
                self.__viewer.set_show_text()
                client.publish(state_topic, "OFF", retain=True)
                self.__viewer.reset_name_tm(pic, self.paused)
        # text_refresh
        elif message.topic == switch_topic_head + "_text_refresh/set":
            state_topic = switch_topic_head + "_text_refresh/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.__viewer.reset_name_tm(pic, self.paused)

        ##### values ########
        # change subdirectory
        elif message.topic == device_id + "/subdirectory":
            self.__logger.info("Recieved subdirectory: %s", msg)
            self.__model.subdirectory = msg
            self.__next_tm = 0
        # date_from
        elif message.topic == device_id + "/date_from":
            self.__logger.info("Recieved date_from: %s", msg)
            try:
                self.__date_from = float(msg)
            except ValueError:
                if len(msg) == 0:
                    msg = '1970/1/1'
                self.__date_from = make_date(msg)
            self.__next_tm = 0
        # date_to
        elif message.topic == device_id + "/date_to":
            self.__logger.info("Recieved date_to: %s", msg)
            try:
                self.__date_to = float(msg)
            except ValueError:
                if len(msg) == 0:
                    msg = '2038/1/1'
                self.__date_to = make_date(msg)
            self.__next_tm = 0
        # fade_time
        elif message.topic == device_id + "/fade_time":
            self.__logger.info("Recieved fade_time: %s", msg)
            self.__model.fade_time = float(msg)
            self.__next_tm = 0
        # time_delay
        elif message.topic == device_id + "/time_delay":
            self.__logger.info("Recieved time_delay: %s", msg)
            self.__model.time_delay = float(msg)
            self.__next_tm = 0
        # brightness
        elif message.topic == device_id + "/brightness":
            self.__logger.info("Recieved brightness: %s", msg)
            self.__viewer.set_brightness(float(msg))


    def publish_sensors(self, image, image_attr):
        device_id = self.__model.get_mqtt_config()['device_id']
        topic_head =  "homeassistant/sensor/" + device_id
        switch_topic_head = "homeassistant/switch/" + device_id
        state_topic = topic_head + "/state"
        state_payload = {}
        # directory sensor
        actual_dir, dir_list = self.__model.get_directory_list()
        state_payload["dir"] = actual_dir
        dir_attr = {}
        dir_attr['directories'] = dir_list
        # image counter sensor
        state_payload["image_counter"] = str(self.__model.get_number_of_files()) 
        # image sensor
        _, tail = os.path.split(image)
        state_payload["image"] = tail
        # date_from
        state_payload["date_from"] = int(self.__date_from)
        # date_to
        state_payload["date_to"] = int(self.__date_to)
        # time_delay
        state_payload["time_delay"] = self.__model.time_delay
        # fade_time
        state_payload["fade_time"] = self.__model.fade_time

        # send last will and testament
        available_topic = switch_topic_head + "/available"
        self.__client.publish(available_topic, "online", qos=0, retain=True)

        #pulish sensors
        attributes_topic = topic_head + "_image/attributes"
        self.__client.publish(attributes_topic, json.dumps(image_attr), qos=0, retain=False)
        attributes_topic = topic_head + "_dir/attributes"
        self.__client.publish(attributes_topic, json.dumps(dir_attr), qos=0, retain=False)
        self.__logger.info("Send state: %s", state_payload)
        self.__client.publish(state_topic, json.dumps(state_payload), qos=0, retain=False)
