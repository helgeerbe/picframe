import logging
import sys


from picframe import model, viewer_display, controller, interface_kbd



def main():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    logger = logging.getLogger("picture_frame.py")
    logger.info('starting %s', sys.argv)
    if len(sys.argv) > 1:
        m = model.Model(sys.argv[1])
    else:
        m = model.Model()
    
    v = viewer_display.ViewerDisplay(m.get_viewer_config())
    c = controller.Controller(m, v)
    c.start()
    if m.get_model_config()['use_kbd'] == True:
        interface_kbd.InterfaceKbd(c) # TODO make kbd failsafe
    mqtt_config = m.get_mqtt_config()
    mqtt = None
    if mqtt_config['use_mqtt'] == True:
        from picframe import interface_mqtt
        mqtt = interface_mqtt.InterfaceMQTT(c, mqtt_config)
        mqtt.start()
    c.loop()
    if mqtt_config['use_mqtt'] == True:
       mqtt.stop() 
    c.stop()


if __name__=="__main__": 
    main() 