#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright © 2013 by Lasse Fister <commander@graphicore.de>
# 
# This file is part of Multitoner.
#
# Multitoner is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# Multitoner is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import division, print_function, unicode_literals


import os
import json

from gi.repository import Gtk, GObject

from gtk_inks_editor import InksEditor
from gtk_preview import PreviewWindow
from model import ModelCurves, ModelInk
from history import History
from emitter import Emitter
from compatibility import repair_gsignals


__all__ = ['Document']


# just a preparation for i18n
def _(string):
    return string


class Label(Gtk.Grid):
    """ label used in a document tab """
    __gsignals__ = repair_gsignals({
        'close': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                  # id
                  GObject.TYPE_INT, ))
    })
    def __init__(self, id, text):
        Gtk.Grid.__init__(self)
        self.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.set_column_spacing(5)
        #self.set_row_spacing(5)
        
        # icon
        icon = Gtk.Image.new_from_stock(Gtk.STOCK_FILE, Gtk.IconSize.MENU)
        self.attach(icon, 0, 0, 1, 1)
        
        # label 
        self.label = label = Gtk.Label(text)
        self.attach_next_to(label, icon, Gtk.PositionType.RIGHT, 1, 1)
        
        # close button
        button = Gtk.Button()
        button.set_focus_on_click(False)
        button.add(Gtk.Image.new_from_stock(Gtk.STOCK_CLOSE, Gtk.IconSize.MENU))
        button.connect('clicked', self.clicked_handler, id)
        self.attach_next_to(button, label, Gtk.PositionType.RIGHT, 1, 1)
        self.show_all()
    
    def clicked_handler(self, button, id, data=None):
        self.emit('close', id)
    
    def set_label_text(self, text):
        self.label.set_text(text)
    
    def set_changed_indicator(self, has_changes):
        _class = 'has-changes'
        if has_changes:
            self.get_style_context().add_class(_class)
        else:
            self.get_style_context().remove_class(_class)


class Document(Emitter):
    """ A Multitoner Tool Document.
    
    Hub for Model, Preview, History and InksEditor etc.
    """
    file_extension = '.mtt' # .m(ulti)t(oner)t(ool)
    untitled_name = _('untitled')
    def __init__(self, gradient_worker, preview_worker, filename=None, data=None):
        if data is None:
            data = {}
        self._gradient_worker = gradient_worker
        self._preview_worker = preview_worker
        
        model = ModelCurves(ChildModel=ModelInk, **data)
        model.add(self)
        history = History(model)
        inks_editor = InksEditor(model, self._gradient_worker)
        inks_editor.connect('open-preview', self.open_preview_handler)
        
        self.id = id(self)
        label = Label(self.id, self.untitled_name)
        
        self.history = history
        self.model = model
        self.widget = inks_editor
        self.label = label
        self.filename = filename
        
        self._preview_windows = []
    
    @classmethod
    def new_from_file(Cls, gradient_worker, preview_worker, filename):
        with open(filename, 'r') as f:
            data = json.load(f)
        return Cls(gradient_worker, preview_worker, filename, data)
    
    def trigger_on_document_state_update(self, *args):
        for item in self._subscriptions:
            item.on_document_state_update(self, *args)
    
    @property
    def has_changes(self):
        return getattr(self, '_has_changes', False)
    
    @has_changes.setter
    def has_changes(self, value):
        old = self.has_changes
        self._has_changes = not not value
        if old != self._has_changes:
            self.label.set_changed_indicator(self._has_changes)
        self.trigger_on_document_state_update() 
    
    def on_model_updated(self, model, event, *args):
        """ 
        model updates are used as indicator that the history changed as well
        """
        self.has_changes = True
    
    @property
    def filename(self):
        return getattr(self, '_filename', None)
    
    @filename.setter
    def filename(self, value):
        self._filename = value
        if self._filename is None:
            label = self.untitled_name
        else:
            label = os.path.basename(self._filename)
        self.label.set_label_text(label)
        self.label.set_tooltip_text(self._filename or '')
    
    def _save(self, filename):
        data = self.model.get_args()
        data = json.dumps(data, sort_keys=True, indent=2, separators=(',', ': '))
        with open(filename, 'w') as f:
            f.write(data)
        self.has_changes = False
    
    def save(self):
        self._save(self.filename)
    
    def save_as(self, filename):
        self._save(filename)
        self.filename = filename
    
    def destroy(self):
        """ Closes Resources. Only Preview Windows right now. """
        previews = tuple(self._preview_windows)
        for preview in previews:
            preview.destroy()
    
    def destroy_preview_handler(self, widget):
        try:
            self._preview_windows.remove(widget)
        except ValueError: # not in list
            pass
        return True
    
    def open_preview(self):
        preview = PreviewWindow(self._preview_worker, self.model)
        preview.show_all()
        preview.ask_for_image()
        preview.connect('destroy', self.destroy_preview_handler)
        self._preview_windows.append(preview)
    
    def open_preview_handler(self, *args):
        self.open_preview()
