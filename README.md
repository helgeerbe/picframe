picture_frame
=============

* Just another picture frame viewer for raspberry, but with automatic integration into [Home Assistant](https://www.home-assistant.io/) for remote control
* https://github.com/helgeerbe/picture_frame
* Helge Erbe
* Licence: MIT
* Tested on rasberry 3B+ and Python 3.7

This is a viewer for a raspberry powered picture frames. For remote control it provides an automatic integration into [Home Assistant](https://www.home-assistant.io/) via MQTT discovery.

Main highlights in Home Assistant:
* tun on/of display
* auto discovery and selection of image directories
* display number of images (incl. auto discovery of new images)
* date from / date to for images to display
* set image display duration and fading time 
* show next/pevious image, pause, shuffle playlist or sort by name
* extract any exif info from image (like aperture, iso, fnumber, camera model) by config
* provide gps information as longitude/latitude to show image location on a map in Home Assistant

## Quick Install
* `pip3 install picture_frame`
* all configurable items will be installed under `~/.local/picframe` of the current user's home
* copy `~/.local/picframe/config/configuration_example.yaml' to `~/.local/picframe/config/configuration.yaml' and do your settings
* picture_frame makes use of [pi3d](https://github.com/pi3d/pi3d.github.com) which needs some extra config with `sudo raspi-config`. In the raspi-config module, go
  * on **pi 4** to
      * 4 Performance Options > P2 GPU Memory > enter 256
      * 7 Advanced Options > A2 GL Driver > Choose G2 GL Fake KMS.
  * on **pi 3** to
      * 4 Performance Options > P2 GPU Memory > enter 128
      * 6 Advanced Options > A2 GL Driver > Choose G1 (Legacy)
  * Reboot!
* start `picture_frame`

## Configuration
### configuration.yaml
By default picture_frame reads its configuration from `~/.local/picframe/config/configuration.yaml`. To use an other file or path you can provide the config file as the first parameter `picture_frame this/leads/to/my/config.yaml`.
Most parameters have default values, if not provided in the config file.

The configuration is splitted in three sections:
1. Viewer:
  * `blur_amount: 12`   
    *default=12*  
    Larger values than 12 will increase processing load quite a bit.
  * `blur_zoom: 1.0`  
    *default=1.0*  
    Must be >= 1.0 which expands the backgorund to just fill the space around the image.
  * `blur_edges: False`   
    *default=False*  
    Use blurred version of image to fill edges - will override ` fit = False`. 
  * `edge_alpha: 0.5`  
    *default=0.5*  
    Background colour at edge. 1.0 would show reflection of image.
  * `fps: 20.0`  
    *default=20.0*  
    Frames per second to render. Higher values result in higher load.
  * `background: [0.2, 0.2, 0.3, 1.0]`  
    *default=[0.2, 0.2, 0.3, 1.0]*  
    RGBA to fill edges when fitting.
  * `blend_type: 0.0`  
    *default="0.0"*  
    choices={"blend":0.0, "burn":1.0, "bump":2.0}, type of blend the shader can do
  * `font_file: "~/.local/picframe/data/fonts/NotoSans-Regular.ttf"`  
    *default="~/.local/picframe/data/fonts/NotoSans-Regular.ttf"`*
    Font is taken from [GoogleFonts](https://fonts.google.com/specimen/Noto+Sans)
  * `shader: "~/.local/picframe/data/shaders/blend_new"`  
    *default="~/.local/picframe/data/shaders/blend_new"*  
    The shader ist taken from [pi3d_demos](https://github.com/pi3d/pi3d_demos). If you like to play with it. Download the demo package. There are lots of shaders.
  * `show_names_tm: 0.0`  
    *default=0.0*  
    Time to show text over image with file name.
  * `fit: False`  
    *default=False*  
    Shrink to fit screen (i.e. don't crop").
  * `auto_resize: True`  
    *default=True*  
    Set this to False if you want to use 4K resolution on Raspberry Pi 4.    
    You should ensure your images are the correct size for the display.  
  * `kenburns: False`  
    *default=False*  
    Will set `fit->False` and `blur_edges->False`.
  
2. Model:
  * `pic_dir: "~/Pictures"`  
    *default="~/Pictures"*  
    Root folder for images.
  * `no_files_img: "~/.local/picframe/data/no_pictures.jpg"`
    *default="~/.local/picframe/data/no_pictures.jpg"*   
    Image to show if none selected.
  * `subdirectory: ""`  
    *default=""*  
    Subdir of pic_dir - can be changed by MQTT.
  * `check_dir_tm: 60.0`  
    *default=60.0*  
    Interval for checking for direcectory and file changes.
  * `recent_n: 3`  
    *default=3*  
    When shuffling the keep n most recent ones to play before the rest.
  * `reshuffle_num: 1`  
    *default=1*  
    Times through before re-shuffling.
  * `time_delay: 200.0`  
    *default=200.0*  
    Time between consecutive slide starts - can be changed by MQTT.
  * `fade_time: 10.0`  
    *default=10.0*  
    Change time during which slides overlap - can be changed by MQTT.
  * `shuffle: True`  
    *default=True*  
    Shuffle on reloading image files - can be changed by MQTT.
  * `image_attr: [`  
    `'PICFRAME GPS',`  
    `'EXIF FNumber',`  
    `'EXIF ExposureTime',`  
    `'EXIF ISOSpeedRatings',`  
    `'EXIF FocalLength',`  
    `'EXIF DateTimeOriginal',`  
    `'Image Model']`  
    *default= ['PICFRAME GPS']*  
    picture_frame uses [exifread](https://github.com/ianare/exif-py) to extract the image meta data.  

    Note that the dictionary keys are the IFD name followed by the tag name. For example:  
    `'EXIF DateTimeOriginal', 'Image Orientation', 'MakerNote FocusMode'`  

    **Tag Descriptions**  
    Tags are divided into these main categories:  
    * Image: information related to the main image (IFD0 of the Exif data).
    * Thumbnail: information related to the thumbnail image, if present (IFD1 of the Exif data).
    * EXIF: Exif information (sub-IFD).
    * GPS: GPS information (sub-IFD).
    * Interoperability: Interoperability information (sub-IFD).
    * MakerNote: Manufacturer specific information. There are no official published references for these tags.
    * 'PICFRAME GPS' is special to picframe. It retrieves the GPS info as longitude/latitude pair. So you can show the image location in Home Assistant on a map.

3. MQTT:                                     
  * `server: "your_mqtt_broker"`  
    Host name of your MQTT broker
  * `port: 8883`  
    Default = 8883 for tls, 1883 else (tls must be "" then !!!!!)
  * `login: "name"`  
    Your MQTT user.
  * `password: "your_password"`  
    Password for MQTT user.
  * `tls: "/path/to/your/ca.crt"`  
    File name including path to your 'ca.crt'. If not used, must be set to "" !!!!
  * `device_id: 'picframe'`  
  *default='picframe'*  
    Unique id of device. Change if there is more than one picture frame. Home Assistant uses this id as the device name.

### Running as service
I'm using systemd to run picture_frame as a servie.  
Create `/etc/systemd/system/picture_frame.service`
``` 
[Unit]
Description=picture frame on pi
After=multi-user.target

[Service]
Type=idle

User=pi
ExecStart=/home/pi/.local/bin/picture_frame

Restart=always

[Install]
WantedBy=multi-user.target
```
Commands:  
* **Enable:** `sudo systemctl enable picture_frame.service`
* **Disable:** `sudo systemctl disable picture_frame.service`
* **Start:** `sudo systemctl start picture_frame.service`
* **Stop:** `sudo systemctl stop picture_frame.service`

### Home Assistant
The image shows a sample integration into Home Assistant.  
![Image of Home Assistant integration](https://github.com/helgeerbe/picture_frame/blob/dev/screenshots/hass_integration.PNG)  
Assuming you use `picframe` as `device_id`. Home Assistant shows the following entities:
1. Switches

  entity | function
  ------ | --------
  switch.picframe_display | Switch to turn on/of the display.
  switch.picframe_back | Each toggle of the switch goes one image back
  switch.picframe_next | Each toggle of the switch goes one image forward
  switch.picframe_paused | Switch to pause/continue slide show
  switch.picframe_shuffle | Switch on shuffle list, off sort list by filename

2. Sensors

  entity | state | attributes 
  ------ | ----- | ----------
  sensor.picframe_date_from | actual filter for date_from as timestamp in seconds since 1970-01-01 |
  sensor.picframe_date_to | actual filter for date_to as timestamp in seconds since 1970-01-01 |
  sensor.picframe_image | file name | image Metadata as configured in `image_attr`
  sensor.picframe_dir | name of actual selected subdirectory or root of image directory | list of subdirectories
  sensor.picframe_image_counter | number of files below selected directory | 
  sensor.picframe_time_delay | actual setting for delay | 
  sensor.picframe_fade_time | actual setting fading time | 

3. MQTT  

Assuming you use `picframe` as `device_id`. picture_frame subscribes to the following topics to recieve settings.

  topic | command
  ----- | -------
  picframe/date_from | timestamp attribute from input_datetime entity
  picframe/date_to | timestamp attribute from input_datetime entity
  picframe/fade_time | state from input_number entity
  picframe/time_delay | state from input_number entity
  picframe/subdirectory | state from input_select entity

```
My example yaml sniplet config from the above image could be found unter ~/.local/picframe/examples.
```

## Documentation
Please note that picture_frame may change significantly during its development.
Bug reports, comments, feature requests and fixes are most welcome!
## Acknowledgement
When I started 2019 my DIY project building a raspberry powered digital picture frame I came across Wolfgang's website [www.thedigitalpictureframe.com](https://www.thedigitalpictureframe.com/). Many Thanks to Wolfgang for your inspiring work. I ran my frame with the [pi3d PictureFrame2020.py](https://github.com/pi3d/pi3d_demos) viewer, but always missed a more deeply integration to my smart home server running [Home Assistant](https://www.home-assistant.io/).

A special Thank to the [pi3d](https://github.com/pi3d/pi3d_demos) project. You are doing a great job!

As my personel corona project I decided to rewrite the viewer to my needs. Maybe someone can make use of it.

