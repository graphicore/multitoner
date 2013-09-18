#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

from gi.repository import Gtk

class ActionGroup(Gtk.ActionGroup):
    def __init__(*args):
        Gtk.ActionGroup.__init__(*args)

    def add_icon_action(self, name , label=None, tooltip=None,
                        icon_name=None, callback=None, accelerator=None,
                        stock_id=None, type=None):
        if type is None:
            type = Gtk.Action
        action = type(name, label, tooltip, stock_id)
        if icon_name is not None:
            action.set_icon_name(icon_name)
        if callback is not None:
            action.connect('activate', callback)
        
        if accelerator is not None:
            self.add_action_with_accel(action, accelerator)
        else:
            self.add_action(action)
    
    def add_icon_actions(self, actions):
        for action in actions:
            self.add_icon_action(*action)
