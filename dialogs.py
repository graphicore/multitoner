#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

from gi.repository import Gtk, GObject, Gdk

# just a preparation for i18n
def _(string):
    return string


class OpenImageDialog(object):
    def __init__(self, window):
        self.window = window
    
    def _runFileOpenDialog(self):
        dialog = Gtk.FileChooserDialog(title=_('Open Image File for Preview')
            , parent=self.window
            , action=Gtk.FileChooserAction.OPEN
            , buttons=( Gtk.STOCK_CANCEL
                      , Gtk.ResponseType.CANCEL
                      , Gtk.STOCK_OPEN
                      , Gtk.ResponseType.ACCEPT
            )
        )
        image_filter = Gtk.FileFilter()
        image_filter.add_mime_type('image/*')
        dialog.set_filter(image_filter)
        
        filename = None
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            filename = dialog.get_filename()
        dialog.destroy()
        return filename
    
    def execute(self):
        filename = self._runFileOpenDialog()
        return filename

def _showMessageDialog(message_type, window, message, moreInfo=None):
    dialog = Gtk.MessageDialog(
        window
        , Gtk.DialogFlags.DESTROY_WITH_PARENT
        , message_type
        , Gtk.ButtonsType.CLOSE
        , message
    )
    if moreInfo is not None:
        dialog.format_secondary_text(moreInfo)
    
    # Destroy the dialog when the user responds to it
    # (e.g. clicks a button)
    def destroy(*args):
        dialog.destroy()
    dialog.connect('response', destroy)
    dialog.show()
    return dialog

def showErrorDialog(window, message, moreInfo=None):
    return _showMessageDialog(Gtk.MessageType.ERROR, window, message, moreInfo)
    
def showNoticeDialog(window, message, moreInfo=None):
    return _showMessageDialog(Gtk.MessageType.INFO, window, message, moreInfo)
