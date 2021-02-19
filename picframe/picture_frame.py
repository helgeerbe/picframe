import logging
import sys
import argparse
import os
import shutil

from picframe import model, viewer_display, controller, interface_kbd, interface_http, __version__

def copy_files(pkgdir, target):
    fullpath = os.path.join(pkgdir,  target)
    shutil.copytree(fullpath,  os.getcwd() + '/picture_frame/' + target)

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
    parser.add_argument("-w", "--webserver", help="start local webserver",
                        action="store_true")
    args = parser.parse_args()
    if args.initialize:
        pkgdir = sys.modules['picframe'].__path__[0]
        copy_files(pkgdir, 'html')
        copy_files(pkgdir, 'config')
        copy_files(pkgdir, 'examples')
        copy_files(pkgdir, 'data')
        print('created ./picture_frame')
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
    if args.webserver:
        server = interface_http.InterfaceHttp(c, "/home/pi/dev/picture_frame/html") #or wherever - should be in configuration.yaml
    c.loop()
    if mqtt_config['use_mqtt'] == True:
       mqtt.stop() 
    c.stop()


if __name__=="__main__": 
    main() 