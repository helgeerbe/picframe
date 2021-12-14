import inspect
import logging
import subprocess
import sys
import time
import typing

import numpy as np
import pi3d


logger = logging.getLogger(__name__)


class InterfacePeripherals:
    """Opens connections to peripheral interfaces and reacts to their state to handle user input.
    Controls playback (navigation), device display, device power and other things.

    Args:
        model: Model of picframe containing config and business logic.
        viewer: Viewer of picframe representing the display.
        controller: Controller of picframe steering image display.
    """

    def __init__(
        self,
        model: "picframe.model.Model",
        viewer: "picframe.viewer_display.ViewerDisplay",
        controller: "picframe.controller.Controller",
    ) -> None:
        logger.info("creating an instance of InterfacePeripherals")

        self.__model = model
        self.__viewer = viewer
        self.controller = controller

        self.__input_type = self.__model.get_peripherals_config()["input_type"]
        if not self.__input_type:
            logger.info("peripheral input is disabled")
            return
        valid_input_types = {"keyboard", "touch", "mouse"}
        if self.__input_type not in valid_input_types:
            logger.warning(
                "input type '%s' is invalid, valid options are: %s",
                self.__input_type,
                valid_input_types,
            )
            return

        self.__menu_autohide_tm = self.__model.get_viewer_config()["menu_autohide_tm"]
        self.__buttons = self.__model.get_peripherals_config()["buttons"]

        self.__gui = self.__get_gui()
        self.__mouse = self.__get_mouse()
        self.__keyboard = self.__get_keyboard()

        self.__menu_buttons = self.__get_menu_buttons()
        self.__menu_height = (
            min(self.__viewer.display_width, self.__viewer.display_height) // 4 if self.__menu_buttons else 0
        )
        self.__menu = self.__get_menu()
        self.__menu_bg_widget = self.__get_menu_bg_widget()
        self.__back_area, self.__next_area = self.__get_navigation_areas()
        self.__menu_bg = self.__get_menu_bg()
        self.__menu_is_on = False
        self.__mouse_is_down = False
        self.__last_touch_position = None
        self.__last_menu_show_at = 0
        self.__clock_is_suspended = False
        self.__pointer_position = (0, 0)
        self.__timestamp = 0

    def check_input(self) -> None:
        """Checks for any input from the selected peripheral device and handles it."""
        if not self.__input_type:
            return

        if self.__input_type == "keyboard":
            self.__handle_keyboard_input()

        elif self.__input_type in ["touch", "mouse"]:
            self.__timestamp = time.time()
            self.__update_pointer_position()

            if self.__input_type == "touch":
                self.__handle_touch_input()

            elif self.__input_type == "mouse":
                self.__handle_mouse_input()

            # Autohide menu
            if self.menu_is_on:
                if self.__menu_autohide_tm and self.__timestamp - self.__last_menu_show_at > self.__menu_autohide_tm:
                    self.menu_is_on = False
                else:
                    self.__menu_bg.draw()

            self.__gui.draw(*self.__pointer_position)

    def stop(self) -> None:
        """Gracefully stops any active peripheral device."""
        if hasattr(self, "__mouse") and self.__mouse:
            self.__mouse.stop()
        if hasattr(self, "__keyboard") and self.__keyboard:
            self.__keyboard.close()

    @property
    def menu_is_on(self) -> None:
        return self.__menu_is_on

    @menu_is_on.setter
    def menu_is_on(self, val: bool) -> None:
        self.__menu_is_on = val
        if val:
            self.__last_menu_show_at = self.__timestamp
            if self.__viewer.clock_is_on:
                self.__clock_is_suspended = True
                self.__viewer.clock_is_on = False
            self.__menu.show()
        else:
            if self.__clock_is_suspended:
                self.__clock_is_suspended = False
                self.__viewer.clock_is_on = True
            self.__menu.hide()

    def __get_gui(self) -> "pi3d.Gui":
        font = pi3d.Font(
            self.__model.get_viewer_config()["font_file"],
            color=(255, 255, 255, 255),
            font_size=self.__model.get_viewer_config()["menu_text_sz"],
            shadow_radius=3,
            spacing=0,
        )
        return pi3d.Gui(font, show_pointer=self.__input_type == "mouse")

    def __get_mouse(self) -> typing.Optional["pi3d.Mouse"]:
        if self.__input_type in ["touch", "mouse"]:
            mouse = pi3d.Mouse(
                restrict=self.__input_type == "mouse",
                width=self.__viewer.display_width,
                height=self.__viewer.display_height,
            )
            mouse.start()
            return mouse

    def __get_keyboard(self) -> typing.Optional["pi3d.Keyboard"]:
        if self.__input_type == "keyboard":
            return pi3d.Keyboard()

    def __get_menu_buttons(self) -> typing.List["IPMenuItem"]:
        btns = []
        for name, props in self.__buttons.items():
            if not props["enable"]:
                continue
            for _, cls in inspect.getmembers(sys.modules[__name__], inspect.isclass):
                if issubclass(cls, IPMenuItem) and cls is not IPMenuItem and cls.config_name == name:
                    btn = cls(self, self.__gui, props["label"], shortcut=props["shortcut"])
                    btns.append(btn)
        return btns

    def __get_menu(self) -> "pi3d.Menu":
        x = -self.__viewer.display_width // 2
        if self.__input_type == "keyboard":
            # When keyboard is enabled, menu must be constantly shown to allow menu items
            # register `shortcut` keys - instead of hiding it, it is rendered out of view
            x *= -1
        menu = pi3d.Menu(menuitems=self.__menu_buttons, x=x, y=self.__viewer.display_height // 2)
        if self.__input_type != "keyboard":
            menu.hide()
        return menu

    def __get_menu_bg_widget(self) -> "pi3d.util.Gui.Widget":
        """This widget lies between navigation areas and menu buttons.
        It intercepts clicks into the empty menu area which would otherwise trigger navigation.
        """
        array = np.zeros((1, 1, 4), dtype=np.uint8)
        texture = pi3d.Texture(array, blend=True, mipmap=False, free_after_load=True)
        sprite = pi3d.ImageSprite(
            texture,
            self.__gui.shader,
            w=self.__viewer.display_width,
            h=self.__menu_height,
            x=0,
            y=0,
            z=4.0,
        )
        return pi3d.util.Gui.Widget(
            self.__gui,
            sprite,
            x=-self.__viewer.display_width // 2,
            y=self.__viewer.display_height // 2,
        )

    def __get_navigation_areas(
        self,
    ) -> typing.Tuple["pi3d.util.Gui.Widget", "pi3d.util.Gui.Widget"]:
        array = np.array([[[0, 0, 255, 0]]], dtype=np.uint8)
        texture = pi3d.Texture(array, blend=True, mipmap=False, free_after_load=True)
        back_sprite = pi3d.ImageSprite(
            texture,
            self.__gui.shader,
            w=self.__viewer.display_width // 2,
            h=self.__viewer.display_height,
            x=0,
            y=0,
            z=4.0,
        )
        next_sprite = pi3d.ImageSprite(
            texture,
            self.__gui.shader,
            w=self.__viewer.display_width // 2,
            h=self.__viewer.display_height,
            x=0,
            y=0,
            z=4.0,
        )
        # Move left and down by 1 px to register clicks on the screen edges
        back_area = pi3d.util.Gui.Widget(
            self.__gui,
            back_sprite,
            x=-self.__viewer.display_width // 2 - 1,
            y=self.__viewer.display_height // 2 - 1,
            callback=self.__go_back,
            shortcut="a",
        )
        next_area = pi3d.util.Gui.Widget(
            self.__gui,
            next_sprite,
            x=0,
            y=self.__viewer.display_height // 2 - 1,
            callback=self.__go_next,
            shortcut="d",
        )
        return back_area, next_area

    def __get_menu_bg(self) -> "pi3d.ImageSprite":
        array = np.zeros((self.__menu_height, 1, 4), dtype=np.uint8)
        array[:, :, 3] = np.linspace(120, 0, self.__menu_height).reshape(-1, 1)
        texture = pi3d.Texture(array, blend=True, mipmap=False, free_after_load=True)
        return pi3d.ImageSprite(
            texture,
            self.__gui.shader,
            w=self.__viewer.display_width,
            h=self.__menu_height,
            x=0,
            y=int(self.__viewer.display_height // 2 - self.__menu_height // 2),
            z=4.0,
        )

    def __handle_keyboard_input(self) -> None:
        code = self.__keyboard.read_code()
        if len(code) > 0:
            if not self.controller.display_is_on:
                self.controller.display_is_on = True
            else:
                self.__gui.checkkey(code)

    def __handle_touch_input(self) -> None:
        """Due to pi3d not reliably detecting touch as Mouse.LEFT_BUTTON event
        when a touch happens at any position with x or y lower than previous touch,
        any pointer movement is considered a click event.
        """
        if self.__pointer_moved():
            if not self.controller.display_is_on:
                self.controller.display_is_on = True
            elif self.__pointer_position[1] < self.__viewer.display_height // 2 - self.__menu_height:
                # Touch in main area
                if self.menu_is_on:
                    self.menu_is_on = False
                else:
                    self.__handle_click()
            else:
                # Touch in menu area
                if self.menu_is_on:
                    self.__handle_click()
                self.menu_is_on = True  # Reset clock for autohide

    def __handle_mouse_input(self) -> None:
        if self.__pointer_moved() and not self.controller.display_is_on:
            self.controller.display_is_on = True

        # Show or hide menu
        self.menu_is_on = self.__pointer_position[1] > self.__viewer.display_height // 2 - self.__menu_height

        # Detect click
        if self.__mouse.button_status() == self.__mouse.LEFT_BUTTON and not self.__mouse_is_down:
            self.__mouse_is_down = True
            self.__handle_click()
        elif self.__mouse.button_status() != self.__mouse.LEFT_BUTTON and self.__mouse_is_down:
            self.__mouse_is_down = False

    def __update_pointer_position(self) -> None:
        position_x, position_y = self.__mouse.position()
        if self.__input_type == "mouse":
            position_x -= self.__viewer.display_width // 2
            position_y -= self.__viewer.display_height // 2
        elif self.__input_type == "touch":
            # Workaround, pi3d seems to always assume screen ratio 4:3 so touch is incorrectly translated
            # to x, y on screens with a different ratio
            position_y *= self.__viewer.display_height / (self.__viewer.display_width * 3 / 4)
        self.__pointer_position = (position_x, position_y)

    def __pointer_moved(self) -> bool:
        if not self.__last_touch_position:
            self.__last_touch_position = self.__pointer_position

        if self.__last_touch_position != self.__pointer_position:
            self.__last_touch_position = self.__pointer_position
            return True
        return False

    def __handle_click(self) -> None:
        logger.debug("handling click at position x: %s, y: %s", *self.__pointer_position)
        self.__gui.check(*self.__pointer_position)

    def __go_back(self, position) -> None:
        logger.info("navigation: previous picture")
        self.controller.back()

    def __go_next(self, position) -> None:
        logger.info("navigation: next picture")
        self.controller.next()


class IPMenuItem(pi3d.MenuItem):
    """Wrapper around pi3d.MenuItem that implements `action` method.
    In the future, this class can be extended to support toggling of multiple text labels
    (e.g., "Pause"/"Resume").

    A subclass must imlement class variable `config_name` that matches its name in the configuration.
    """

    config_name = ""

    def __init__(self, ip: "InterfacePeripherals", gui: "pi3d.Gui", text: str, shortcut: str) -> None:
        self.ip = ip
        text = "  " + text + "  "
        super().__init__(gui, text=text, callback=self.callback, shortcut=shortcut)

    def callback(self, *args) -> None:
        """
        Logs each action.
        """
        logger.info("invoked menu item: %s", self.config_name)
        self.action()

    def action(self) -> None:
        """
        A subclass must override this method to define its business logic.
        """
        raise NotImplementedError


class PauseMenuItem(IPMenuItem):
    """Pauses or unpauses the playback.
    Navigation to previous or next picture is possible also when the playback is paused.
    """

    config_name = "pause"

    def action(self):
        self.ip.controller.paused = not self.ip.controller.paused


class DisplayOffMenuItem(IPMenuItem):
    """Turns off the display. When the display is off,
    any input from the selected peripheral device will turn it back on.
    """

    config_name = "display_off"

    def action(self):
        self.ip.controller.display_is_on = False


class LocationMenuItem(IPMenuItem):
    """Shows or hides location information."""

    config_name = "location"

    def action(self):
        if self.ip.controller.text_is_on("location"):
            self.ip.controller.set_show_text("location", "OFF")
        else:
            self.ip.controller.set_show_text("location", "ON")


class ExitMenuItem(IPMenuItem):
    """Exits the program."""

    config_name = "exit"

    def action(self):
        self.ip.controller.keep_looping = False


class PowerDownMenuItem(IPMenuItem):
    """Exits the program and shuts down the device. Uses sudo."""

    config_name = "power_down"

    def action(self):
        self.ip.controller.keep_looping = False
        subprocess.check_call(["sudo", "poweroff"])
