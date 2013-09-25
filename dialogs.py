#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import os

from gi.repository import Gtk

__all__ = ['show_open_image_dialog', 'show_save_as_dialog',
           'show_save_as_eps_dialog', 'show_error_dialog',
           'show_notice_dialog', 'show_message']

# just a preparation for i18n
def _(string):
    return string

def show_open_image_dialog(window):
    dialog = Gtk.FileChooserDialog(title=_('Choose an Image-File')
        , parent=window
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

def show_save_as_dialog(window, filename=None, current_name=None):
    dialog = Gtk.FileChooserDialog(title=_('Save File')
        , parent=window
        , action=Gtk.FileChooserAction.SAVE
        , buttons=( Gtk.STOCK_CANCEL
                    , Gtk.ResponseType.CANCEL
                    , Gtk.STOCK_SAVE
                    , Gtk.ResponseType.ACCEPT
        )
    )
    dialog.set_do_overwrite_confirmation(True);
    if current_name is not None:
        dialog.set_current_name(current_name)
    if filename is not None:
        dialog.set_filename(filename)
    result = None
    if dialog.run() == Gtk.ResponseType.ACCEPT:
        result = dialog.get_filename()
    dialog.destroy()
    return result

def show_save_as_eps_dialog(window, source_filename):
    last_dot = source_filename.rfind('.')
    if last_dot == -1:
        name_proposal = source_filename
    else:
        name_proposal = source_filename[0:source_filename.rfind('.')]
    name_proposal = name_proposal + '.eps'
    return show_save_as_dialog(window, name_proposal, os.path.basename(name_proposal))

def _show_message_dialog(message_type, window, message, more_info=None):
    dialog = Gtk.MessageDialog(
        window
        , Gtk.DialogFlags.DESTROY_WITH_PARENT
        , message_type
        , Gtk.ButtonsType.CLOSE
        , message
    )
    if more_info is not None:
        dialog.format_secondary_text(more_info)
    
    # Destroy the dialog when the user responds to it
    # (e.g. clicks a button)
    def destroy(*args):
        dialog.destroy()
    dialog.connect('response', destroy)
    dialog.show()
    return dialog

def show_error_dialog(window, message, more_info=None):
    return _show_message_dialog(Gtk.MessageType.ERROR, window, message, more_info)
    
def show_notice_dialog(window, message, more_info=None):
    return _show_message_dialog(Gtk.MessageType.INFO, window, message, more_info)

def show_message(window, type, message, more_info):
    show_dialog = {
          'error': show_error_dialog
        , 'notice': show_notice_dialog
    }.get(type, None)
    assert type is not None, 'There is no dialog for message type {0}'.format(type)
    
    return show_dialog(window, message, more_info)
