# picture_frame powered by pi3d

1. <a href="#what">What Is picture_frame?</a>
2. <a href="#history">History of picture_frame</a>
3. <a href="#highlights">Highlights of picture_frame</a>
4. <a href="#documentation">Documentation</a>
5. <a href="#acknowledgement">Acknowledgement</a>

<a name="what" />

## What Is picture_frame?

This is a viewer for a raspberry powered picture frame. For remote control it provides an automatic integration into [Home Assistant](https://www.home-assistant.io/) via MQTT discovery.

* https://github.com/helgeerbe/picture_frame
* Paddy Gaunt, Jeff Godfrey, Helge Erbe
* Licence: MIT
* Tested on rasberry 3B+/4, Ubuntu 20.10 and Python 3.7

<a name="history" />

#### History of picture_frame

When I started 2019 my DIY project building a raspberry powered digital picture frame I came across Wolfgang's website [www.thedigitalpictureframe.com](https://www.thedigitalpictureframe.com/). I ran my frame with the [pi3d PictureFrame2020.py](https://github.com/pi3d/pi3d_demos) viewer, but always missed a more deeply integration to my smart home server running [Home Assistant](https://www.home-assistant.io/).As my personel corona project I decided to rewrite the viewer to my needs. Hoping  someone can make use of it.

<a name="highlights" />

### Highlights of picture_frame

* Viewer
  * blend effects
  * auto mat generation
  * overlays (title, location, date, ...)
* Filter by
  * IPTC tags
  * location
  * directories
  * date
* Remote Control
  * control interface for mqtt, http(s)
  * tun on/of display
  * next/prev/pause image
  * shuffle play
  * toggle overlays
  * retrieve image meta info (exif, IPTC)

<a name="documentation" />

## Documentation

[Full documentation can be found at the project's wiki](https://github.com/helgeerbe/picture_frame/wiki).

Please note that picture_frame may change significantly during its development.
Bug reports, comments, feature requests and fixes are most welcome!

<a name="acknowledgement" />

## Acknowledgement

Many Thanks to Wolfgang [www.thedigitalpictureframe.com](https://www.thedigitalpictureframe.com/) for your inspiring work. 

A special Thank to Paddy Gaunt one of the authors of the [pi3d](https://github.com/pi3d/pi3d_demos) project. You are doing a great job!

Last but no least a big Thank You to Jeff Godfrey. Your auto mat feature and database driven cache is an outstanding piece of code.
