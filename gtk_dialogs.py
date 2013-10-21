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

from gi.repository import Gtk, GdkPixbuf

from compatibility import encode

__all__ = ['show_open_image_dialog', 'show_save_as_dialog',
           'show_save_as_eps_dialog', 'show_error_dialog',
           'show_notice_dialog', 'show_message', 'show_about_dialog']

DIRECTORY = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(DIRECTORY, 'VERSION')) as f:
    VERSION = f.read().strip()

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
    dialog.set_do_overwrite_confirmation(True)
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

def _get_scaled_pixbuf(filename, width=None, height=None):
    pb = GdkPixbuf.Pixbuf.new_from_file(filename)

    if width is not None and height is None:
        height = pb.get_height() / pb.get_width() * width
    elif height is not None and width is None:
        width = pb.get_width() / pb.get_height() * height
    
    if height is not None and width is not None:
        pb = pb.scale_simple(width, height, GdkPixbuf.InterpType.HYPER)
    return pb

def show_about_dialog(window):
    link_format = '<a href="http://{1}">{0}</a>'
    email_format = '{0} &lt;<a href="mailto:{0} &lt;{1}&gt;">{1}</a>&gt;'
    ### information
    logo_filename = os.path.join(DIRECTORY, 'assets', 'images',
                                 'multitoner_name.svg')
    program_name='Multitoner'
    short_info = _('Create “Multitone” (Monotone, Duotone, \n'
                   'Tritone, Quadtone, …) EPS-files for printing.')
    website = 'http://somwhere.in.the.web'
    authors = [('Lasse Fister', 'commander@graphicore.de')]
    
    # copyright might change when it goes to FSF or similar, so I don't
    # use the 'authors'-list here.
    copyright_name = 'Lasse Fister'
    copyright_email = 'commander@graphicore.de'
    copyright_info = '<small>Copyright © 2013 by {0}</small>'.format(
                     email_format.format(copyright_name, copyright_email))
    
    license = """
Multitoner is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Multitoner is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see &lt;<a href="{0}">{0}</a>&gt;.
    """.format('http://www.gnu.org/licenses/').strip()
    
    silber_und_blei_website = 'silber-und-blei.com'
    silber_und_blei_logo_filename = os.path.join(DIRECTORY, 'assets', 'images',
                                                'silber-und-blei.svg')
    graphicore_website = 'graphicore.de'
    graphicore_logo_filename = os.path.join(DIRECTORY, 'assets', 'images',
                                           'graphicore.svg')
    license_logo_filename = os.path.join(DIRECTORY, 'assets', 'images',
                                           'gpl-v3.svg')
    
    ### build tabs
    
    # about
    logo = _get_scaled_pixbuf(logo_filename, width=500)
    logo_image = Gtk.Image.new_from_pixbuf(logo)
    logo_image.set_halign(Gtk.Align.CENTER)
    
    program_name_version = Gtk.Label(None)
    program_name_version.set_markup(_('<b>{0}</b> v {1}').format(
                                    program_name, VERSION))
    program_name_version.set_selectable(True)
    
    info = Gtk.Label(short_info)
    info.set_selectable(True)
    
    website_link = Gtk.Label(None)
    website_link.set_markup(link_format.format(_('Project Website'), website))
    website_link.set_selectable(True)
    
    copyright = Gtk.Label(None)
    copyright.set_markup(copyright_info)
    copyright.set_selectable(True)
    
    about_label = Gtk.Label(_('About'))
    about_box = Gtk.Grid()
    for i, widget in enumerate((logo_image, info, program_name_version,
                                website_link, copyright)):
        about_box.attach(widget, 0, i, 1, 1)
    about_tab = (about_box, about_label)
    
    # credits
    credits_label = Gtk.Label(_('Credits'))
    credits_box = Gtk.Grid()
    
    def make_big_credit(logo_filename, praised_for, url, width=None, height=None):
        link = Gtk.Label()
        link.set_markup(praised_for.format(
            link_format.format(url, url)
        ))
        link.set_selectable(True)
        
        logo = Gtk.Image.new_from_pixbuf(
            _get_scaled_pixbuf(logo_filename, width=width, height=height))
        logo.get_style_context().add_class('logo')
        return link, logo
    
    silber_und_blei = make_big_credit(silber_und_blei_logo_filename,
                                      _('Initiated by {0}'),
                                      silber_und_blei_website, width=400)
    graphicore = make_big_credit(graphicore_logo_filename,
                                 _('Initial development by {0}'),
                                 graphicore_website, height=62)
    
    authors_text = '\n'.join(
        ['\t' + email_format.format(name, mail)for name, mail in authors])
    authors_label = Gtk.Label()
    authors_label.set_markup(_('<b>Authors</b>:\n{0}').format(authors_text))
    authors_label.set_selectable(True)
    
    credit_lines = [
          silber_und_blei[0]
        , silber_und_blei[1]
        , graphicore[0]
        , graphicore[1]
        , authors_label
    ]
    for i, line in enumerate(credit_lines):
        credits_box.attach(line, 0, i, 1, 1)
    
    credits_tab = (credits_box, credits_label)
    
    # license
    license_box = Gtk.Grid()
    
    license_logo = _get_scaled_pixbuf(license_logo_filename, width=150)
    license_image = Gtk.Image.new_from_pixbuf(license_logo)
    license_image.set_halign(Gtk.Align.CENTER)
    license_box.attach(license_image, 0, 0, 1, 1)
    
    license_text = Gtk.Label(None)
    license_text.set_markup(license)
    license_text.set_selectable(True)
    
    
    license_label = Gtk.Label(_('License'))
    
    license_box.attach(license_text, 0, 1, 1, 1)
    
    license_tab = (license_box, license_label)
    
    ### fill the tabs
    tabs = Gtk.Notebook()
    for tab in (about_tab, credits_tab, license_tab):
        tabs.append_page(*tab)
        tab[0].set_halign(Gtk.Align.CENTER)
        tab[0].set_valign(Gtk.Align.CENTER)
    
    ### build the Dialog
    about = Gtk.Dialog(parent=window
        , title=_('About {0}').format(program_name)
        , buttons=(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        , flags=Gtk.DialogFlags.DESTROY_WITH_PARENT
    )
    about.set_resizable(False)
    about.get_style_context().add_class('about-window')
    about.set_border_width(5) # FIXME: How can this be done via CSS?
    
    about.connect('response', lambda widget, __:widget.destroy())
    
    content_area = about.get_content_area()
    content_area.get_style_context().add_class('content')
    
    content_area.add(tabs)
    
    content_area.show_all()
    about.show()
