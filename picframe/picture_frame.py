import logging
import sys
import argparse

from picframe import model, viewer_display, controller, interface_kbd, interface_http, __version__



def main():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    logger = logging.getLogger("picture_frame.py")
    logger.info('starting %s', sys.argv)

    
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-i", "--initialize", help="creates standard file structure for picture_frame in current directory",
                        action="store_true")
    group.add_argument("-v", "--version", help="print version information",
                        action="store_true")
    group.add_argument("configfile", nargs='?', help="/path/to/configuration.yaml")
    args = parser.parse_args()
    if args.initialize:
        print("initialize turned on")
        return
    elif args.version:
        print("picture_frame version: ", __version__) # TODO Dump required modules and their versions
        return
    elif args.configfile:
        m = model.Model(args.configfile)
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
    server = interface_http.InterfaceHttp(c, "/home/pi/dev/picture_frame/html") #or wherever - should be in configuration.yaml
    c.loop()
    if mqtt_config['use_mqtt'] == True:
       mqtt.stop() 
    c.stop()


if __name__=="__main__": 
    main() 