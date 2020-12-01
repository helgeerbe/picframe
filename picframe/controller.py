import logging
import time
import paho.mqtt.client as mqtt

class Controller:

    def __init__(self, model, viewer):
        self.__logger = logging.getLogger("controller.Controller")
        self.__logger.info('creating an instance of Controller')
        self.__model = model
        self.__viewer = viewer
    
    def loop(self):
        next_tm = time.time() + self.__model.time_delay
        next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']
        next_file, orientation, image_attr = self.__model.get_next_file()
        
        while self.__viewer.slideshow_is_running(next_file, orientation, self.__model.time_delay, self.__model.fade_time):
            tm = time.time()
            next_file = None
            if tm > next_tm:
                next_tm = tm + self.__model.time_delay
                next_file, orientation, image_attr = self.__model.get_next_file()
                
            if self.__viewer.is_in_transition() == False: # safe to do long running tasks
                if tm > next_check_tm:
                    self.__model.check_for_file_changes()
                    next_check_tm = time.time() + self.__model.get_model_config()['check_dir_tm']

    
    def start(self):
        self.__viewer.slideshow_start()

    def stop(self):
        self.__viewer.slideshow_stop()
    
    def on_connect(client, userdata, flags, rc):
        self.__logger.info('Connected with mqtt broker')
        
        # send last will and testament
        client.publish("homeassistant/switch/picframe/available", "online", qos=0, retain=True)
        
        client.subscribe("frame/date_from", qos=0)
        client.subscribe("frame/date_to", qos=0)
        client.subscribe("frame/time_delay", qos=0)
        client.subscribe("frame/fade_time", qos=0)
        client.subscribe("frame/shuffle", qos=0)
        client.subscribe("frame/quit", qos=0)
        client.subscribe("frame/paused", qos=0)
        client.subscribe("frame/back", qos=0)
        client.subscribe("frame/subdirectory", qos=0)
        client.subscribe("frame/delete", qos=0)
        client.subscribe( "homeassistant/switch/picframe/set" , qos=0)
        # send configuration topic for image counter sensor
        client.publish("homeassistant/sensor/sensorPicframeImages/config", '{"name":"images", "icon":"mdi:camera-burst", "state_topic":"homeassistant/sensor/sensorPicframe/state",  "unit_of_measurement": "Bilder", "value_template": "{{ value_json.imageCounter}}", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_ic", "dev":{"ids":["picframe"]}}', qos=0, retain=True)
        # send  configuration for image sensor metadata
        client.publish("homeassistant/sensor/sensorPicframeGpsLat/config", '{"name":"latitude", "state_topic":"homeassistant/sensor/sensorPicframe/state", "value_template": "{{ value_json.latitude}}", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_lat", "dev":{"ids":["picframe"]}}', qos=0, retain=True)
        client.publish("homeassistant/sensor/sensorPicframeGpsLon/config", '{"name":"longitude", "state_topic":"homeassistant/sensor/sensorPicframe/state", "value_template": "{{ value_json.longitude}}", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_ion", "dev":{"ids":["picframe"]}}', qos=0, retain=True)
        client.publish("homeassistant/sensor/sensorPicframeFnumber/config", '{"name":"fnumber", "icon":"mdi:camera-iris", "state_topic":"homeassistant/sensor/sensorPicframe/state",  "unit_of_measurement": "f", "value_template": "{{ value_json.fnumber}}", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_fnum", "dev":{"ids":["picframe"]}}', qos=0, retain=True)
        client.publish("homeassistant/sensor/sensorPicframeExposure/config", '{"name":"exposure", "icon":"mdi:camera-timer", "state_topic":"homeassistant/sensor/sensorPicframe/state",  "unit_of_measurement": "sec", "value_template": "{{ value_json.exposure}}", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_exp", "dev":{"ids":["picframe"]}}', qos=0, retain=True)
        client.publish("homeassistant/sensor/sensorPicframeIso/config", '{"name":"iso", "icon":"mdi:film", "state_topic":"homeassistant/sensor/sensorPicframe/state",  "unit_of_measurement": "ISO", "value_template": "{{ value_json.iso}}", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_iso", "dev":{"ids":["picframe"]}}', qos=0, retain=True)
        client.publish("homeassistant/sensor/sensorPicframeFocallength/config", '{"name":"focallength", "icon":"mdi:signal-distance-variant", "state_topic":"homeassistant/sensor/sensorPicframe/state",  "unit_of_measurement": "mm", "value_template": "{{ value_json.focallength}}", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_fl", "dev":{"ids":["picframe"]}}', qos=0, retain=True)
        client.publish("homeassistant/sensor/sensorPicframeModel/config", '{"name":"model", "icon":"mdi:camera", "state_topic":"homeassistant/sensor/sensorPicframe/state", "value_template": "{{ value_json.model}}", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_mod", "dev":{"ids":["picframe"]}}', qos=0, retain=True)
        client.publish("homeassistant/sensor/sensorPicframeImagedate/config", '{"name":"imagedate", "icon":"mdi:calendar-clock", "state_topic":"homeassistant/sensor/sensorPicframe/state", "value_template": "{{ value_json.imagedate}}", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_id", "dev":{"ids":["picframe"]}}', qos=0, retain=True)
        client.publish("homeassistant/sensor/sensorPicframeFilename/config", '{"name":"filename", "icon":"mdi:file-image", "state_topic":"homeassistant/sensor/sensorPicframe/state", "value_template": "{{ value_json.filename}}", "json_attributes_topic":"homeassistant/sensor/sensorPicframe/attributes", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_fn", "dev":{"ids":["picframe"]}}', qos=0, retain=True)

        # send configuration topic and display state
        client.publish("homeassistant/switch/picframe/config", '{"name":"display", "icon":"mdi:panorama", "command_topic":"homeassistant/switch/picframe/set", "pl_off":"OFF", "pl_on":"ON", "state_topic":"homeassistant/switch/picframe/state", "avty_t":"homeassistant/switch/picframe/available", "pl_avail":"online", "pl_not_avail":"offline", "uniq_id":"picframe_rl_1", "dev":{"ids":["picframe"], "name":"Picframe", "mdl":"Picture Frame", "sw":"1.0.0.", "mf":"erbehome"}}', qos=0, retain=True)
        CONTROL = "vcgencmd"
        CONTROL_BLANK = [CONTROL, "display_power"]
        state = str(subprocess.check_output(CONTROL_BLANK))
        if (state.find("display_power=1") != -1):
            client.publish("homeassistant/switch/picframe/state", "ON", qos=0, retain=True)
        else :
            client.publish("homeassistant/switch/picframe/state", "OFF", qos=0, retain=True)