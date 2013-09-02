#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
import sys
from gi.repository import Gtk, Gdk, GObject

# just a preparation for i18n
def _(string):
    return string

UI_INFO = """
<ui>
  <menubar name='MenuBar'>
    <menu action='FileMenu'>
      <menuitem action='FileNew' />
      <separator />
      <menuitem action='FileQuit' />
    </menu>
  </menubar>
</ui>
"""

class Multitoner(Gtk.Grid):
    def __init__(self):
        Gtk.Grid.__init__(self)

        #self.documentActions = Gtk.ActionGroup('document_actions')
        
        self.globalActions = self.makeGlobalActions()

        uimanager = Gtk.UIManager()
        uimanager.add_ui_from_string(UI_INFO)
        
        uimanager.insert_action_group(self.globalActions)
        
        menubar = uimanager.get_widget("/MenuBar")        
        self.attach(menubar, 0, 0, 1, 1)

        #toolbar = uimanager.get_widget("/ToolBar")
        
        # this removes the immediate dependency to window
        def onRealize(widget, *args):
            """ 
            closure to connect to window when it establishes this widget
            """
            window = widget.get_toplevel()
            # Add the accelerator group to the toplevel window
            accelgroup = uimanager.get_accel_group()
            window.add_accel_group(accelgroup)
            # connect just once ever
            widget.disconnect(realize_handler_id)
        #save realize_handler_id for the closure of onRealize 
        realize_handler_id = self.connect('realize' , onRealize)

    def makeGlobalActions(self):
        actionGroup = Gtk.ActionGroup('global_actions')
        actionGroup.add_actions([
              ('FileMenu', None, 'File', None,
               None, None)
            , ('FileNew', Gtk.STOCK_NEW, 'New …', '<Ctrl>n',
               'Start a new document.', self.menuFileNewHandler)
            , ('FileQuit', Gtk.STOCK_QUIT, 'Quit', '<ctrl>q',
               None, self.menuFileQuitHandler)
            ])
        return actionGroup
    
    def menuFileNewHandler(self, widget):
        print 'new file handler'
    
    def menuFileQuitHandler(self, widget):
        Gtk.main_quit()

if __name__ == '__main__':
    GObject.threads_init()
    use_gui, __ = Gtk.init_check(sys.argv)
    window = Gtk.Window()
    window.set_title(_('Multitoner Tool'))
    window.set_default_size(640, 480)
    window.set_has_resize_grip(True)
    # the theme should do so
    window.set_border_width(5)    
    window.connect('destroy', Gtk.main_quit)
    
    cssProvider = Gtk.CssProvider()
    cssProvider.load_from_path('style.css')
    screen = window.get_screen()
    styleContext = Gtk.StyleContext()
    styleContext.add_provider_for_screen(screen, cssProvider,
        Gtk.STYLE_PROVIDER_PRIORITY_USER)
    
    multitoner = Multitoner()
    window.add(multitoner)
    
    window.show_all()
    Gtk.main()
