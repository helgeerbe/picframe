import logging
import sys
import argparse
import os
import ssl
import locale
from distutils.dir_util import copy_tree

from picframe import model, viewer_display, controller, interface_kbd, interface_http, __version__

PICFRAME_DATA_DIR = 'picframe_data'

def copy_files(pkgdir, dest, target):
    try:
        fullpath = os.path.join(pkgdir,  target)
        destination = os.path.join(dest,  PICFRAME_DATA_DIR)
        destination = os.path.join(destination,  target)
        copy_tree(fullpath,  destination)
    except:
        raise

def create_config(root):
    fullpath_root = os.path.join(root,  PICFRAME_DATA_DIR)
    fullpath = os.path.join(fullpath_root, 'config')
    source = os.path.join(fullpath, 'configuration_example.yaml')
    destination = os.path.join(fullpath, 'configuration.yaml')
    run_start = os.path.join(fullpath_root, 'run_start.py') # TODO for work-around on RPi4

    try:
        with open (source, "r") as file:
            filedata = file.read()

        print("This will configure ", destination)
        print("To keep default, just hit enter")

        # replace all paths with selected picframe_data path
        filedata = filedata.replace("~/picframe_data", fullpath_root)

        #pic_dir
        pic_dir= input("Enter picture directory [~/Pictures]: ")
        if pic_dir == "":
            pic_dir = "~/Pictures" # convert to absolute path too for work-around on RPi4 running as root
        pic_dir = os.path.expanduser(pic_dir)
        filedata = filedata.replace("~/Pictures", pic_dir)

        #deleted_pictures
        deleted_pictures = input("Enter picture directory [~/DeletedPictures]: ")
        if deleted_pictures == "":
            deleted_pictures = "~/DeletedPictures"
        deleted_pictures = os.path.expanduser(deleted_pictures)
        filedata = filedata.replace("~/DeletedPictures", deleted_pictures)

        #locale
        lan, enc = locale.getlocale()
        if not lan:
            (lan, enc) = ("en_US", "utf8")
        param = input("Enter locale [" + lan + "." + enc + "]: ") or (lan + "." + enc)
        filedata = filedata.replace("en_US.utf8", param)

        with open (destination, "w") as file:
            file.write(filedata)

        with open (run_start, "w") as file: # TODO work-around for RPi4
            file.write("from picframe import start\nstart.main()\n")
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
        if os.geteuid() == 0:
            print("Don't run the initialize step with sudo. It might put the files in the wrong place!")
            return
        pkgdir = sys.modules['picframe'].__path__[0]
        try: 
            dest = os.path.abspath(os.path.expanduser(args.initialize))
            copy_files(pkgdir, dest, 'html')
            copy_files(pkgdir, dest, 'config')
            copy_files(pkgdir, dest, 'data')
            create_config(dest)
            print('created {}/picframe_data'.format(dest))
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