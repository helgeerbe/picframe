"""Controller of picture_frame."""

import logging
import time
import paho.mqtt.client as mqtt
import json
import os
from picframe import __version__


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
        self.__next_tm = 0.0
        self.__date_from = time.mktime((1970, 1, 1, 0, 0, 0, 0, 0, 0))
        self.__date_to = time.mktime((2038, 1, 1, 0, 0, 0, 0, 0, 0))

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
        self.__next_tm = 0.0

    def back(self):
        self.__model.set_next_file_to_privious_file()
        self.__next_tm = 0.0

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
            next_file = None
            orientation = 1
            if not self.paused and tm > self.__next_tm:
                self.__next_tm = tm + self.__model.time_delay
                next_file, orientation, image_attr = self.__model.get_next_file(self.date_from, self.date_to)
                self.publish_sensors(next_file, image_attr)
                
            if self.__viewer.is_in_transition() == False: # safe to do long running tasks
                if tm > next_check_tm:
                    self.__model.check_for_file_changes()
                    next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']
            
            if self.__viewer.slideshow_is_running(next_file, orientation, time_delay, fade_time) == False:
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
        
        # send display switch configuration  and display state
        config_topic = switch_topic_head + "_display/config"
        command_topic = switch_topic_head + "_display/set"
        state_topic = switch_topic_head + "_display/state"
        config_payload = '{"name":"' + device_id + '_display", "icon":"mdi:panorama", "command_topic":"' + command_topic + '", "state_topic":"' + state_topic + '", "avty_t":"' + available_topic + '", "uniq_id":"' + device_id + '_disp", "dev":{"ids":["' + device_id + '"], "name":"' + device_id + '", "mdl":"Picture Frame", "sw":"' + __version__ + '", "mf":"erbehome"}}'
        client.subscribe(command_topic , qos=0)
        client.publish(config_topic, config_payload, qos=0, retain=True)
        if self.__viewer.display_is_on == True:
            client.publish(state_topic, "ON", qos=0, retain=True)
        else :
            client.publish(state_topic, "OFF", qos=0, retain=True)
        
        # send shuffle switch configuration  and shuffle state
        config_topic = switch_topic_head + "_shuffle/config"
        command_topic = switch_topic_head + "_shuffle/set"
        state_topic = switch_topic_head + "_shuffle/state"
        config_payload = '{"name":"' + device_id + '_shuffle", "icon":"mdi:shuffle-variant", "command_topic":"' + command_topic + '", "state_topic":"' + state_topic + '", "avty_t":"' + available_topic + '", "uniq_id":"' + device_id + '_shuf", "dev":{"ids":["' + device_id + '"]}}'
        client.subscribe(command_topic , qos=0)
        client.publish(config_topic, config_payload, qos=0, retain=True)
        if self.__model.shuffle == True:
            client.publish(state_topic, "ON", qos=0, retain=True)
        else :
            client.publish(state_topic, "OFF", qos=0, retain=True)
        
        # send paused switch configuration and paused state
        config_topic = switch_topic_head + "_paused/config"
        command_topic = switch_topic_head + "_paused/set"
        state_topic = switch_topic_head + "_paused/state"
        config_payload = '{"name":"' + device_id + '_paused", "icon":"mdi:pause", "command_topic":"' + command_topic + '", "state_topic":"' + state_topic + '", "avty_t":"' + available_topic + '", "uniq_id":"' + device_id + '_paused", "dev":{"ids":["' + device_id + '"]}}'
        client.subscribe(command_topic , qos=0)
        client.publish(config_topic, config_payload, qos=0, retain=True)
        if self.paused == True:
            client.publish(state_topic, "ON", qos=0, retain=True)
        else :
            client.publish(state_topic, "OFF", qos=0, retain=True)
        
        # send back switch configuration  and back state
        config_topic = switch_topic_head + "_back/config"
        command_topic = switch_topic_head + "_back/set"
        state_topic = switch_topic_head + "_back/state"
        config_payload = '{"name":"' + device_id + '_back", "icon":"mdi:skip-previous", "command_topic":"' + command_topic + '", "state_topic":"' + state_topic + '", "avty_t":"' + available_topic + '", "uniq_id":"' + device_id + '_back", "dev":{"ids":["' + device_id + '"]}}'
        client.subscribe(command_topic , qos=0)
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.publish(state_topic, "OFF", qos=0, retain=True)

        # send next switch configuration  and next state
        config_topic = switch_topic_head + "_next/config"
        command_topic = switch_topic_head + "_next/set"
        state_topic = switch_topic_head + "_next/state"
        config_payload = '{"name":"' + device_id + '_next", "icon":"mdi:skip-next", "command_topic":"' + command_topic + '", "state_topic":"' + state_topic + '", "avty_t":"' + available_topic + '", "uniq_id":"' + device_id + '_next", "dev":{"ids":["' + device_id + '"]}}'
        client.subscribe(command_topic , qos=0)
        client.publish(config_topic, config_payload, qos=0, retain=True)
        client.publish(state_topic, "OFF", qos=0, retain=True)


    def on_message(self, client, userdata, message):
        device_id = self.__model.get_mqtt_config()['device_id']
        msg = message.payload.decode("utf-8") 
        switch_topic_head = "homeassistant/switch/" + device_id

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
            elif msg == "OFF":
                self.__model.shuffle = False
                client.publish(state_topic, "OFF", retain=True)
        # paused
        elif message.topic == switch_topic_head + "_paused/set":
            state_topic = switch_topic_head + "_paused/state"
            if msg == "ON":
                self.paused = True
                client.publish(state_topic, "ON", retain=True)
            elif msg == "OFF":
                self.paused = False
                client.publish(state_topic, "OFF", retain=True)
        # back buttons
        elif message.topic == switch_topic_head + "_back/set":
            state_topic = switch_topic_head + "_back/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.back()
        # next buttons
        elif message.topic == switch_topic_head + "_next/set":
            state_topic = switch_topic_head + "_next/state"
            if msg == "ON":
                client.publish(state_topic, "OFF", retain=True)
                self.next()
        # next buttons
        elif message.topic == device_id + "/subdirectory":
            self.__logger.info("Recieved subdirectory: %s", msg)
            self.__model.subdirectory = msg
            self.__next_tm = 0
        # date_from
        elif message.topic == device_id + "/date_from":
            self.__logger.info("Recieved date_from: %s", msg)
            self.__date_from = float(msg)
            self.__next_tm = 0
        # date_to
        elif message.topic == device_id + "/date_to":
            self.__logger.info("Recieved date_to: %s", msg)
            self.__date_to = float(msg) 
            self.__next_tm = 0
        # fade_time
        elif message.topic == device_id + "/fade_time":
            self.__logger.info("Recieved fade_time: %s", msg)
            self.__model.fade_time = float(msg)
            self.__next_tm = 0
        # fade_time
        elif message.topic == device_id + "/time_delay":
            self.__logger.info("Recieved time_delay: %s", msg)
            self.__model.time_delay = float(msg)
            self.__next_tm = 0
            
            
    
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
        