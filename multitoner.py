#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
import sys
from gi.repository import Gtk, Gdk, GObject
from gtkinktool import InksEditor, ModelCurves, ModelInk, History, GradientWorker

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

class Label(Gtk.Grid):
    __gsignals__ = {
        'close': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                  # id
                  GObject.TYPE_INT, ))
    }
    def __init__(self, id, text):
        Gtk.Grid.__init__(self)
        self.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.set_column_spacing(5)
        #self.set_row_spacing(5)
        
        
        # icon
        icon = Gtk.Image.new_from_stock(Gtk.STOCK_FILE, Gtk.IconSize.MENU)
        self.attach(icon, 0, 0, 1, 1)
        
        # label 
        label = Gtk.Label(text)
        self.attach_next_to(label, icon, Gtk.PositionType.RIGHT, 1, 1)
        
        # close button
        button = Gtk.Button()
        button.set_focus_on_click(False)
        button.add(Gtk.Image.new_from_stock(Gtk.STOCK_CLOSE, Gtk.IconSize.MENU))
        button.connect('clicked', self.clickedHandler, id)
        self.attach_next_to(button, label, Gtk.PositionType.RIGHT, 1, 1)
        self.show_all()
    def clickedHandler(self, button, id, data=None):
        self.emit("close", id)

class Multitoner(Gtk.Grid):
    def __init__(self, documents):
        Gtk.Grid.__init__(self)
        self._gradientWorker = GradientWorker()
        self._documents = documents
        self._activeDocument = None
        #self.documentActions = Gtk.ActionGroup('document_actions')
        
        self._globalActions = self.makeGlobalActions()
        menubar = self.initMenu()
        self.attach(menubar, 0, 0, 1, 1)
        self._notebook = Gtk.Notebook()
        self._notebook.set_scrollable(True)
        def switchPageHandler(widget, page, page_num):
            print 'switchPage', page, page_num
            self._activeDocument = id(widget)
            return True
            
        self._notebook.connect('switch-page', switchPageHandler)
        self.attach(self._notebook, 0, 1, 1, 1)
        
    def initMenu(self):
        uimanager = Gtk.UIManager()
        uimanager.add_ui_from_string(UI_INFO)
        uimanager.insert_action_group(self._globalActions)
        menubar = uimanager.get_widget("/MenuBar")
        
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
        return menubar

    def makeGlobalActions(self):
        actionGroup = Gtk.ActionGroup('global_actions')
        actionGroup.add_actions([
              ('FileMenu', None, 'File', None,
               None, None)
            , ('FileNew', Gtk.STOCK_NEW, _('New …'), '<Ctrl>n',
               _('Start a new document.'), self.menuFileNewHandler)
            , ('FileQuit', Gtk.STOCK_QUIT, _('Quit'), '<ctrl>q',
               None, self.menuFileQuitHandler)
            ])
        return actionGroup
    
    def menuFileNewHandler(self, widget):
        self.makeNewDocument()
    
    def closeDocumentHandler(self, widget, id, *data):
        page = self._notebook.page_num(self._documents[id]['widget'])
        self._notebook.remove_page(page)
        # Todo: ask when there are unsafed changes
        del self._documents[id]
    
    def makeNewDocument(self):
        model = ModelCurves(ChildModel=ModelInk)
        history = History(model)
        inksEditor = InksEditor(model, self._gradientWorker)
        widget_id = id(inksEditor)
        self._documents[widget_id] = {
            'history': history,
            'model': model,
            'widget': inksEditor
        }
        label = Label(widget_id, _('new Document*'))
        label.connect('close', self.closeDocumentHandler, widget_id)
        self._notebook.append_page(inksEditor, label)
        self._notebook.set_tab_reorderable(inksEditor, True)
        inksEditor.show_all()
        return widget_id
        
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
    
    documents = {}
    multitoner = Multitoner(documents)
    window.add(multitoner)
    
    window.show_all()
    Gtk.main()
