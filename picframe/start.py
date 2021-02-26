import logging
import sys
import argparse
import os
import ssl
from distutils.dir_util import copy_tree

from picframe import model, viewer_display, controller, interface_kbd, interface_http, __version__

def copy_files(pkgdir, dest, target):
    try:
        fullpath = os.path.join(pkgdir,  target)
        copy_tree(fullpath,  dest + '/picframe/' + target)
    except:
        raise

def check_packages (packages):
    for package in packages:
        try:
            if package == 'paho.mqtt':
                import paho.mqtt
                print(package, ': ',paho.mqtt.__version__)
            elif package == 'ninepatch':
                import ninepatch
                print(package, ': installed, but no version info')
            else:
                print(package, ': ',__import__(package).__version__)
        except ImportError:
            print(package, ': Not found!')

def main():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    logger = logging.getLogger("start.py")
    logger.info('starting %s', sys.argv)

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-i", "--initialize",
                        help="creates standard file structure for picframe in destination directory",
                        metavar=('DESTINATION_DIRECTORY'))
    group.add_argument("-v", "--version", help="print version information",
                        action="store_true")
    group.add_argument("configfile", nargs='?', help="/path/to/configuration.yaml")
    args = parser.parse_args()
    if args.initialize:
        pkgdir = sys.modules['picframe'].__path__[0]
        try: 
            copy_files(pkgdir, args.initialize, 'html')
            copy_files(pkgdir, args.initialize, 'config')
            copy_files(pkgdir, args.initialize, 'data')
            print('created ',args.initialize,'/picframe')
        except Exception as e:
            print("Can't copy files to: ", args.initialize, ". Reason: ", e)
        return
    elif args.version:
        print("picframe version: ", __version__)
        print("\nChecking required packages......")
        required_packages=[
            'PIL',
            'exifread',
            'pi3d',
            'yaml',
            'paho.mqtt',
            'iptcinfo3',
            'numpy',
            'ninepatch'
        ]
        check_packages(required_packages)
        print("\nChecking optional packages......")
        check_packages(['pyheif'])
        return
    elif args.configfile:
        m = model.Model(args.configfile)
    else:
        m = model.Model()

    v = viewer_display.ViewerDisplay(m.get_viewer_config())
    c = controller.Controller(m, v)
    c.start()

    if m.get_model_config()['use_kbd']:
        interface_kbd.InterfaceKbd(c) # TODO make kbd failsafe

    mqtt_config = m.get_mqtt_config()
    if mqtt_config['use_mqtt']:
        from picframe import interface_mqtt
        mqtt = interface_mqtt.InterfaceMQTT(c, mqtt_config)
        mqtt.start()

    http_config = m.get_http_config()
    model_config = m.get_model_config()
    if http_config['use_http']:
        server = interface_http.InterfaceHttp(c, http_config['path'], model_config['pic_dir'], model_config['no_files_img'], http_config['port'])
        if http_config['use_ssl']:
            server.socket = ssl.wrap_socket(
                server.socket,
                keyfile = http_config['keyfile'],
                certfile = http_config['certfile'],
                server_side=True)
    c.loop()
    if mqtt_config['use_mqtt']:
        mqtt.stop()
    if http_config['use_http']: #TODO objects living in multiple threads issue at shutdown!
        server.stop()
    c.stop()


if __name__=="__main__": 
    main() 